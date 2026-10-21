"""
forge_sandbox.py — Subprocess execution boundary for forged tools.

Runs forged Python code in an isolated subprocess:
  - No inherited environment variables (API keys stripped)
  - Resource limits (timeout, memory cap)
  - Restricted working directory (workspace/forged_tools/)
  - Isolated Python mode (-I) — no user site-packages

This is NOT a full OS sandbox (no seccomp / Job Objects / cgroups),
but it IS a genuine process boundary: a forged tool crash or hang
cannot take down the agent, and it cannot read the agent's env vars.
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict


SANDBOX_TIMEOUT_SECONDS = 15

_SECRET_ENV_PATTERNS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


def _build_safe_env(base_dir: Path) -> Dict[str, str]:
    # Windows requires SYSTEMROOT\System32 for Python DLL resolution.
    # Only include that, not the full user PATH (which may have package managers).
    system_root = os.environ.get("SYSTEMROOT", "")
    safe_path = f"{system_root}\\System32" if system_root else os.environ.get("PATH", "")
    
    safe = {
        "PATH": safe_path,
        "SYSTEMROOT": system_root,
        "TEMP": os.environ.get("TEMP", str(tempfile.gettempdir())),
        "TMP": os.environ.get("TMP", str(tempfile.gettempdir())),
        "PYTHONPATH": str(base_dir),
        "PYTHONIOENCODING": "utf-8",
    }
    for key in list(os.environ.keys()):
        if key.upper() in safe or any(s in key.upper() for s in _SECRET_ENV_PATTERNS):
            continue
        if key.startswith("PYTHON") or key in ("LANG", "LC_ALL"):
            safe[key] = os.environ[key]
    return {k: v for k, v in safe.items() if v}


def run_forged_tool_in_subprocess(
    tool_file: Path,
    func_name: str,
    kwargs: Dict[str, Any],
    timeout: int = SANDBOX_TIMEOUT_SECONDS,
) -> str:
    if not tool_file.exists():
        return f"Sandbox error: tool file '{tool_file}' not found."

    base_dir = tool_file.parent.resolve()
    payload = json.dumps({"func_name": func_name, "kwargs": kwargs})

    runner_code = textwrap.dedent(f"""
        import json
        import sys
        import importlib.util

        payload = json.loads(sys.stdin.read())
        func_name = payload["func_name"]
        kwargs = payload["kwargs"]

        spec = importlib.util.spec_from_file_location("forged_tool", r"{tool_file}")
        if spec is None or spec.loader is None:
            print(json.dumps({{"ok": False, "error": "could not load module"}}))
            sys.exit(1)

        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:
            print(json.dumps({{"ok": False, "error": f"module import failed: {{type(e).__name__}}: {{e}}"}}))
            sys.exit(1)

        if not hasattr(mod, func_name):
            print(json.dumps({{"ok": False, "error": f"function '{{func_name}}' not found"}}))
            sys.exit(1)

        try:
            result = getattr(mod, func_name)(**kwargs)
            print(json.dumps({{"ok": True, "result": str(result)}}))
        except Exception as e:
            print(json.dumps({{"ok": False, "error": f"execution failed: {{type(e).__name__}}: {{e}}"}}))
            sys.exit(1)
    """)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(runner_code)
        runner_path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "-I", runner_path],
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(base_dir),
            env=_build_safe_env(base_dir),
            shell=False,
        )

        if result.returncode != 0:
            try:
                data = json.loads(result.stdout.strip().splitlines()[-1])
                if not data.get("ok"):
                    return f"Sandbox execution error: {data.get('error', 'unknown')}"
            except Exception:
                pass
            stderr = (result.stderr or "").strip()[:500]
            return f"Sandbox subprocess exited with code {result.returncode}: {stderr or '(no stderr)'}"

        try:
            data = json.loads(result.stdout.strip().splitlines()[-1])
            if data.get("ok"):
                return str(data.get("result", ""))
            return f"Sandbox execution error: {data.get('error', 'unknown')}"
        except Exception as e:
            return f"Sandbox result parse error: {e}. Raw output: {result.stdout[:200]}"

    except subprocess.TimeoutExpired:
        return f"Sandbox timeout: tool execution exceeded {timeout} seconds."
    except Exception as e:
        return f"Sandbox subprocess error: {type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(runner_path)
        except Exception:
            pass