"""
forge.py - Self-Evolving Autonomous Tool Forge for BERU AI AGENT.
Includes FEATURE 50: Self-Modification Guardrails.

Safety model:
  - New tools require explicit user approval before activation.
  - Every overwrite creates a timestamped backup first.
  - Dangerous imports/patterns are rejected at forge time.
  - Rollback restores the last known-good version of a tool.
  - All activations/rejections/rollbacks are logged to forge_audit.jsonl.
"""
import ast
import json
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import FORGE_DIR
from gateway import ask_ai

REGISTRY_FILE = FORGE_DIR / "registry.json"
PENDING_FILE = FORGE_DIR / "pending.json"
AUDIT_FILE = FORGE_DIR / "forge_audit.jsonl"
BACKUP_DIR = FORGE_DIR / "backups"

_lock = threading.RLock()

# Live in-memory registry of dynamic tools
ACTIVE_FORGED_TOOLS: Dict[str, Callable] = {}
FORGED_SCHEMAS: List[Dict[str, Any]] = []

# Pending proposals awaiting user approval: name -> {description, code, schema, sample_input, created_at}
PENDING_TOOLS: Dict[str, Dict[str, Any]] = {}

# Dangerous patterns that are rejected outright.
# The goal is not to sandbox Python (impossible) but to refuse the obvious footguns.
DANGEROUS_IMPORTS = {
    "ctypes",  # can call arbitrary memory
}
DANGEROUS_CALLS = {
    "os.system",
    "os.popen",
    "subprocess.Popen",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_output",
    "eval",
    "exec",
    "compile",
    "__import__",
    "shutil.rmtree",
    "os.remove",
    "os.rmdir",
    "os.unlink",
    "pty.spawn",
    "socket.socket",  # raw sockets — allow only known-safe usage via explicit allow-list below
}
# Functions that ARE allowed to use subprocess (whitelisted by tool name)
SUBPROCESS_ALLOWLIST: set = set()


# --------------------------------------------------------------------------- #
# File helpers
# --------------------------------------------------------------------------- #
def _ensure_dirs() -> None:
    FORGE_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _load_registry() -> Dict[str, Any]:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_registry(data: Dict[str, Any]) -> None:
    _ensure_dirs()
    REGISTRY_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_pending() -> Dict[str, Any]:
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_pending(data: Dict[str, Any]) -> None:
    _ensure_dirs()
    PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _audit(event: str, tool_name: str, details: Optional[Dict[str, Any]] = None) -> None:
    _ensure_dirs()
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event,
        "tool": tool_name,
        "details": details or {},
    }
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _backup_existing(tool_file: Path) -> Optional[Path]:
    """Copy existing tool file to a timestamped backup before overwriting."""
    if not tool_file.exists():
        return None
    _ensure_dirs()
    stamp = time.strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"{tool_file.stem}.{stamp}.py"
    try:
        shutil.copy2(tool_file, backup)
        return backup
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Static safety checks
# --------------------------------------------------------------------------- #
def _validate_syntax(code: str) -> Tuple[bool, str]:
    try:
        ast.parse(code)
        return True, "Valid syntax."
    except SyntaxError as se:
        return False, f"Syntax Error at line {se.lineno}: {se.msg}"


def _check_dangerous_patterns(code: str, func_name: str) -> Tuple[bool, str]:
    """
    Parse the AST and reject if any dangerous call is present.
    This is not a sandbox — it's a footgun filter.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # Already handled by _validate_syntax
        return True, "Skipped (invalid syntax, handled separately)."

    issues: List[str] = []

    for node in ast.walk(tree):
        # Reject dangerous imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in DANGEROUS_IMPORTS:
                    issues.append(f"dangerous import '{alias.name}'")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in DANGEROUS_IMPORTS:
                issues.append(f"dangerous import from '{node.module}'")
            # Also reject "from os import system; system(...)" — the call site has FQN "system"
            if node.module:
                for alias in node.names:
                    constructed = f"{node.module}.{alias.name}"
                    if constructed in DANGEROUS_CALLS:
                        issues.append(f"dangerous imported symbol '{constructed}' (as '{alias.asname or alias.name}')")

        # Reject dangerous calls
        if isinstance(node, ast.Call):
            fqn = _call_fqn(node.func)
            if fqn in DANGEROUS_CALLS:
                # Allow subprocess ONLY if this tool is whitelisted
                if fqn.startswith("subprocess.") and func_name in SUBPROCESS_ALLOWLIST:
                    continue
                issues.append(f"dangerous call '{fqn}'")

    if issues:
        return False, "Rejected by safety filter: " + "; ".join(sorted(set(issues)))
    return True, "Passed safety filter."


def _call_fqn(func_node: ast.AST) -> str:
    """Return the fully-qualified name of a call node, e.g. 'subprocess.run'."""
    parts: List[str] = []
    cur = func_node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _smoke_test_function(func_name: str, code: str, sample_kwargs: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Compile-only check. Does NOT execute the function.
    Real execution is deferred to activation (which requires explicit approval).
    """
    try:
        compiled = compile(code, f"<forge_{func_name}>", "exec")
    except SyntaxError as se:
        return False, f"Syntax Error at line {se.lineno}: {se.msg}"
    except Exception as e:
        return False, f"Compilation failed: {type(e).__name__}: {e}"

    # Verify the target symbol exists without running anything.
    try:
        tree = ast.parse(code)
        defined = any(
            (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name)
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", None) == func_name for t in n.targets))
            for n in tree.body
        )
        if not defined:
            return False, f"Function '{func_name}' not defined in provided code."
    except Exception as e:
        return False, f"AST check failed: {e}"

    return True, "Compiled and symbol found (execution deferred to activation)."


# --------------------------------------------------------------------------- #
# Proposal (Step 1 — the agent proposes a tool; nothing goes live yet)
# --------------------------------------------------------------------------- #
def forge_new_tool(
    name: str,
    description: str,
    code: str,
    parameters_schema: Dict[str, Any],
    sample_input: Optional[Dict[str, Any]] = None,
    confirm: bool = False,
) -> str:
    """
    Proposes or activates a new tool.

    Behavior:
      - confirm=False (default): validate, smoke-test, store as PENDING. Returns
        a message telling the user the exact call needed to activate.
      - confirm=True: activate immediately (only allowed if the proposal already
        passed validation, OR if validate+smoke-test passes here).

    Feature 50 guardrail: activation requires explicit confirm=True.
    """
    func_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
    if not func_name or not func_name.isidentifier():
        return f"Failed: '{name}' does not produce a valid Python identifier."

    if not isinstance(parameters_schema, dict) or parameters_schema.get("type") != "object":
        return "Failed: parameters_schema must be a JSON-Schema object with 'type': 'object'."

    sample_args = sample_input or {}

    with _lock:
        # ---------------------------------------------------------------- #
        # Step A — validate + safety + smoke test
        # ---------------------------------------------------------------- #
        ok, msg = _validate_syntax(code)
        if not ok:
            _audit("forge_rejected", func_name, {"reason": msg})
            return f"Failed to forge tool '{func_name}': {msg}"

        ok, msg = _check_dangerous_patterns(code, func_name)
        if not ok:
            _audit("forge_rejected", func_name, {"reason": msg})
            return f"Failed to forge tool '{func_name}': {msg}"

        ok, smoke_res = _smoke_test_function(func_name, code, sample_args)
        if not ok:
            # Attempt one self-healing round via LLM
            repair_prompt = f"""The proposed function `{func_name}` failed its smoke test.
Sample Inputs: {json.dumps(sample_args)}
Failure Traceback: {smoke_res}

Code:
{code}

Fix the code so it executes without error. Output ONLY the raw Python code."""
            try:
                fix_resp = ask_ai(
                    [{"role": "user", "content": repair_prompt}], temperature=0.1
                ).content
                clean_fix = re.sub(r"^```python\s*|\s*```$", "", fix_resp.strip(), flags=re.MULTILINE)
                ok2, smoke_res2 = _smoke_test_function(func_name, clean_fix, sample_args)
                if ok2:
                    code = clean_fix
                else:
                    _audit("forge_rejected", func_name, {"reason": f"smoke failed: {smoke_res2}"})
                    return f"Failed smoke test for '{func_name}': {smoke_res2}"
            except Exception:
                _audit("forge_rejected", func_name, {"reason": f"smoke failed: {smoke_res}"})
                return f"Failed smoke test: {smoke_res}"

        # ---------------------------------------------------------------- #
        # Step B — if not confirmed, store as PENDING and return instructions
        # ---------------------------------------------------------------- #
        if not confirm:
            pending = _load_pending()
            pending[func_name] = {
                "name": func_name,
                "description": description,
                "code": code,
                "parameters_schema": parameters_schema,
                "sample_input": sample_args,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            _save_pending(pending)
            PENDING_TOOLS[func_name] = pending[func_name]
            _audit("forge_proposed", func_name, {"description": description[:80]})
            preview = code[:400] + ("..." if len(code) > 400 else "")
            return (
                f"PROPOSED TOOL — awaiting approval.\n"
                f"Name: {func_name}\n"
                f"Description: {description}\n"
                f"Code preview:\n{preview}\n\n"
                f"To activate, call: approve_tool('{func_name}')\n"
                f"To reject, call:   reject_tool('{func_name}')"
            )

        # ---------------------------------------------------------------- #
        # Step C — activate (confirm=True)
        # ---------------------------------------------------------------- #
        return _activate_tool(func_name, description, code, parameters_schema)


def _activate_tool(
    func_name: str,
    description: str,
    code: str,
    parameters_schema: Dict[str, Any],
) -> str:
    """Internal activation — assumes validation has already passed."""
    # Ensure dirs
    _ensure_dirs()

    tool_file = FORGE_DIR / f"{func_name}.py"

    # Backup existing version if overwriting
    backup = _backup_existing(tool_file)

    # Write new file
    try:
        tool_file.write_text(code, encoding="utf-8")
    except Exception as e:
        return f"Failed to write tool file '{tool_file}': {e}"

    # 🛡️ NO IN-PROCESS IMPORT.
    # We do NOT call exec_module() here. Forged code is NEVER loaded into the
    # agent process. Registration only records the file path; every invocation
    # is routed through `run_forged_tool_in_subprocess` in forge_sandbox.py.
    #
    # This closes the "top-level code runs before sandbox" gap: forged tools
    # cannot execute any code — not even at import time — inside the agent.
    if not tool_file.exists():
        return f"Failed: tool file '{tool_file}' was not written."

    # Post-approval runtime smoke test.
    # By this point the user has explicitly approved the tool, so running it
    # once with the proposed sample input is safe.
        # Post-approval runtime smoke test — executed in a SUBPROCESS.
    # This is the ONLY place forged code runs at all, and it runs in the sandbox.
    try:
        from forge_sandbox import run_forged_tool_in_subprocess
        pending_meta = _load_pending().get(func_name) or {}
        sample_kwargs = pending_meta.get("sample_input") or {}
        if sample_kwargs:
            smoke_result = run_forged_tool_in_subprocess(
                tool_file=tool_file,
                func_name=func_name,
                kwargs=sample_kwargs,
                timeout=15,
            )
            if smoke_result.startswith(("Sandbox error", "Sandbox execution", "Sandbox subprocess", "Sandbox timeout", "Sandbox result")):
                raise RuntimeError(smoke_result)
    except Exception as e:
        # Do not leave a broken tool registered.
        if backup and backup.exists():
            try:
                shutil.copy2(backup, tool_file)
            except Exception:
                pass
        else:
            try:
                tool_file.unlink(missing_ok=True)
            except Exception:
                pass
        _audit("forge_smoke_failed", func_name, {"error": f"{type(e).__name__}: {e}"[:300]})
        return (
            f"Activation aborted: '{func_name}' failed its post-approval smoke test "
            f"({type(e).__name__}: {e}). The tool has NOT been registered."
        )

    # Register schema — no fn_obj, because we never loaded the module.
    schema = {
        "type": "function",
        "function": {
            "name": func_name,
            "description": f"[Forged Tool] {description}",
            "parameters": parameters_schema,
        },
    }

    # Update live registry with a MARKER (path, not callable).
    # The dispatcher in agent.py checks ACTIVE_FORGED_TOOLS and routes
    # the call through run_forged_tool_in_subprocess.
    ACTIVE_FORGED_TOOLS[func_name] = tool_file  # path marker, NOT a callable

    existing_idx = next(
        (i for i, s in enumerate(FORGED_SCHEMAS) if s["function"]["name"] == func_name),
        -1,
    )
    if existing_idx >= 0:
        FORGED_SCHEMAS[existing_idx] = schema
    else:
        FORGED_SCHEMAS.append(schema)

    # Persist to registry.json
    reg = _load_registry()
    reg[func_name] = {
        "name": func_name,
        "description": description,
        "file": str(tool_file),
        "schema": schema,
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "backup": str(backup) if backup else None,
    }
    _save_registry(reg)

    # Remove from pending if there
    pending = _load_pending()
    if func_name in pending:
        del pending[func_name]
        _save_pending(pending)
    PENDING_TOOLS.pop(func_name, None)

    _audit("forge_activated", func_name, {"backup": str(backup) if backup else None})
    return (
        f"ACTIVATED tool '{func_name}'. It is now live in your toolbelt.\n"
        f"Backup: {backup if backup else 'none (new tool)'}"
    )


# --------------------------------------------------------------------------- #
# Approval / rejection
# --------------------------------------------------------------------------- #
def approve_tool(name: str) -> str:
    """Activate a previously proposed tool after user approval."""
    func_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
    with _lock:
        pending = _load_pending()
        if func_name not in pending:
            return f"Failed: '{func_name}' is not in the pending queue. Use list_pending_tools() to see pending tools."

        item = pending[func_name]
        result = _activate_tool(
            func_name,
            item["description"],
            item["code"],
            item["parameters_schema"],
        )
        _audit("forge_approved", func_name)
        return result


def reject_tool(name: str) -> str:
    """Reject a pending tool proposal."""
    func_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
    with _lock:
        pending = _load_pending()
        if func_name not in pending:
            return f"Failed: '{func_name}' is not in the pending queue."
        del pending[func_name]
        _save_pending(pending)
        PENDING_TOOLS.pop(func_name, None)
        _audit("forge_rejected_by_user", func_name)
        return f"Rejected and discarded pending tool '{func_name}'."


def list_pending_tools() -> str:
    """List all tools currently waiting for approval."""
    pending = _load_pending()
    if not pending:
        return "No pending tool proposals."
    lines = [f"Pending tools ({len(pending)}):"]
    for name, item in pending.items():
        lines.append(
            f"• {name} — {item.get('description', '')[:80]}  "
            f"(proposed {item.get('created_at', 'unknown')})"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Rollback (Feature 50 — undo a self-modification)
# --------------------------------------------------------------------------- #
def rollback_tool(name: str) -> str:
    """Deactivate a live forged tool and restore its last backup if present."""
    func_name = re.sub(r"[^a-zA-Z0-9_]", "_", name.lower().strip())
    with _lock:
        reg = _load_registry()
        if func_name not in reg:
            return f"Failed: '{func_name}' is not a registered forged tool."

        meta = reg[func_name]
        tool_file = Path(meta["file"])
        backup = meta.get("backup")

        # 1. Try to restore backup to disk
        restored = False
        if backup:
            backup_path = Path(backup)
            if backup_path.exists():
                try:
                    shutil.copy2(backup_path, tool_file)
                    restored = True
                except Exception:
                    pass

        # 2. Remove from live registries either way
        ACTIVE_FORGED_TOOLS.pop(func_name, None)
        FORGED_SCHEMAS[:] = [s for s in FORGED_SCHEMAS if s["function"]["name"] != func_name]
        del reg[func_name]
        _save_registry(reg)

        # 3. If restored from backup, re-register as PATH MARKER — no in-process import.
        if restored:
            try:
                # 🛡️ SECURITY: Do NOT exec_module() here. Forged code never runs
                # in the agent process. We only register the file path.
                ACTIVE_FORGED_TOOLS[func_name] = tool_file
                schema = meta["schema"]
                FORGED_SCHEMAS.append(schema)
                reg[func_name] = meta
                _save_registry(reg)
                _audit("forge_rollback_restored", func_name)
                return f"Rolled back '{func_name}' to previous backup. It is still live."
            except Exception as e:
                _audit("forge_rollback_partial", func_name, {"error": str(e)[:200]})
                return f"Rolled back '{func_name}' — file restored but reload failed: {e}"

        _audit("forge_rollback_removed", func_name)
        return f"Rolled back '{func_name}' — removed from toolbelt (no backup to restore)."

# --------------------------------------------------------------------------- #
# Startup hot-load
# --------------------------------------------------------------------------- #
def hot_load_existing_tools() -> int:
    """
    Load all previously activated forged tools on startup.

    🛡️ SECURITY: We do NOT call exec_module() here. Forged code is NEVER
    imported into the agent process. We only register the file path as
    a marker — every invocation routes through run_forged_tool_in_subprocess.
    """
    with _lock:
        reg = _load_registry()
        loaded = 0
        for name, meta in list(reg.items()):
            f_path = Path(meta["file"])
            if not f_path.exists():
                continue
            try:
                # Register the PATH as the marker (not the loaded function).
                ACTIVE_FORGED_TOOLS[name] = f_path

                # Re-register the schema.
                existing_idx = next(
                    (i for i, s in enumerate(FORGED_SCHEMAS) if s["function"]["name"] == name),
                    -1,
                )
                if existing_idx >= 0:
                    FORGED_SCHEMAS[existing_idx] = meta["schema"]
                else:
                    FORGED_SCHEMAS.append(meta["schema"])
                loaded += 1
            except Exception:
                continue

        # Load pending into memory
        pending = _load_pending()
        for name, item in pending.items():
            PENDING_TOOLS[name] = item

        return loaded