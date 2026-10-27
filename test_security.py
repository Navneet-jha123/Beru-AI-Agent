"""
test_security.py — Automated regression tests for BERU AI Agent security hardening.
Run: pytest test_security.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))


# =========================================================================== #
# Telegram Fail-Closed (Item 1)
# =========================================================================== #
def test_telegram_denies_when_config_missing(monkeypatch):
    import config
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", "")

    # Import fresh so the module sees the empty config
    import importlib
    import telegram_gateway
    importlib.reload(telegram_gateway)

    class FakeUser:
        id = "999999"
    class FakeUpdate:
        effective_user = FakeUser()

    assert telegram_gateway._is_authorized(FakeUpdate()) is False


def test_telegram_allows_configured_admin(monkeypatch):
    import config
    monkeypatch.setattr(config, "TELEGRAM_USER_ID", "12345")

    import importlib
    import telegram_gateway
    importlib.reload(telegram_gateway)

    class FakeUser:
        id = "12345"
    class FakeUpdate:
        effective_user = FakeUser()

    assert telegram_gateway._is_authorized(FakeUpdate()) is True


# =========================================================================== #
# Path Containment (Item 5)
# =========================================================================== #
def test_path_containment_rejects_system32():
    from modes.developer import is_safe_dev_path
    assert is_safe_dev_path("C:/Windows/System32/cmd.exe") is False


def test_path_containment_allows_workspace():
    from modes.developer import is_safe_dev_path
    from config import WORKSPACE_DIR
    assert is_safe_dev_path(str(WORKSPACE_DIR / "test.py")) is True


def test_read_project_file_rejects_system_paths():
    from modes.developer import read_project_file
    result = read_project_file("C:/Windows/System32/drivers/etc/hosts")
    assert "Access Denied" in result or "Failed" in result


def test_apply_code_patch_rejects_system_paths():
    from modes.developer import apply_code_patch
    result = apply_code_patch(
        "C:/Windows/System32/test.exe", "old", "new"
    )
    assert "Access Denied" in result or "Failed" in result


# =========================================================================== #
# Shell Restrictions (Item 2)
# =========================================================================== #
def test_run_dev_command_rejects_shell_metacharacters():
    from modes.developer import run_dev_command
    assert "metacharacter" in run_dev_command("echo hi; rm -rf /").lower()
    assert "metacharacter" in run_dev_command("python -c 'x' | cat").lower()


def test_run_dev_command_rejects_unsafe_executables():
    from modes.developer import run_dev_command
    result = run_dev_command("evil_binary --do-harm")
    assert "not in safe allowlist" in result.lower()


def test_run_dev_command_allows_python():
    from modes.developer import run_dev_command
    result = run_dev_command("python --version")
    assert "Success" in result or "Python" in result


# =========================================================================== #
# Hacker Authorization Gate (Item 4)
# =========================================================================== #
def test_hacker_gate_rejects_without_confirmation():
    from agent import _user_has_confirmed_scan
    assert _user_has_confirmed_scan("scan example.com", None, target="example.com") is False


def test_hacker_gate_rejects_generic_confirmation():
    """Generic 'confirmed' without the target must NOT authorize a scan."""
    from agent import _user_has_confirmed_scan
    assert _user_has_confirmed_scan(
        "yes confirmed", None, target="example.com"
    ) is False


def test_hacker_gate_rejects_confirmation_for_different_target():
    """Confirming one target must NOT authorize a scan of a different target."""
    from agent import _user_has_confirmed_scan
    assert _user_has_confirmed_scan(
        "yes, I confirm authorization to scan evil.com", None, target="example.com"
    ) is False


def test_hacker_gate_accepts_with_confirmation():
    from agent import _user_has_confirmed_scan
    assert _user_has_confirmed_scan(
        "CONFIRM SCAN: example.com", None, target="example.com"
    ) is True


def test_hacker_gate_rejects_old_phrase():
    from agent import _user_has_confirmed_scan
    assert _user_has_confirmed_scan(
        "yes, I confirm authorization to scan example.com", None, target="example.com"
    ) is False


def test_hacker_gate_rejects_history_confirmation():
    """Confirmation must be in the CURRENT message, not prior history."""
    from agent import _user_has_confirmed_scan
    history = [
        {"role": "user", "content": "CONFIRM SCAN: example.com"},
        {"role": "assistant", "content": "Understood. What next?"},
    ]
    assert _user_has_confirmed_scan("scan example.com", history, target="example.com") is False


# =========================================================================== #
# Forge Env Isolation (Item 3, partial)
# =========================================================================== #
def test_forge_does_not_execute_at_proposal_time():
    import tempfile
    from forge import forge_new_tool, reject_tool

    canary = Path(tempfile.gettempdir()) / "beru_test_canary.txt"
    if canary.exists():
        canary.unlink()

    test_name = "canary_test_pytest"
    code = f'open(r"{canary}", "w").write("pwned")\ndef {test_name}():\n    pass'

    try:
        forge_new_tool(
            name=test_name,
            description="test",
            code=code,
            parameters_schema={"type": "object", "properties": {}},
            sample_input={},
            confirm=False,
        )
        # The proposal must NOT have executed the code
        assert not canary.exists(), "Forged code executed at proposal time!"
    finally:
        # Clean up: reject the proposal so it doesn't pollute the pending queue
        try:
            reject_tool(test_name)
        except Exception:
            pass
        # Clean up: remove canary if it somehow appeared
        if canary.exists():
            canary.unlink()


# =========================================================================== #
# Benchmark Enforcement (Item 7)
# =========================================================================== #
def test_benchmark_requires_min_5_tasks():
    from benchmarks import run_benchmark_suite
    result = run_benchmark_suite(subset=["gen_health", "gen_open_calc"])
    assert "minimum 5" in result.lower()


def test_benchmark_reports_tool_failures():
    """Inspect the source to confirm failure detection is wired in."""
    import inspect
    from benchmarks import _run_one
    src = inspect.getsource(_run_one)
    assert "tool_failures" in src
    assert "_on_result" in src

# =========================================================================== #
# Malicious Code Pre-Execution Scanner
# =========================================================================== #
def test_malicious_code_scanner_detects_os_remove():
    from agent import _scan_for_malicious_code
    issues = _scan_for_malicious_code("import os\nos.remove('file.txt')")
    assert len(issues) > 0, "Scanner failed to detect os.remove"


def test_malicious_code_scanner_detects_walk_c_drive():
    from agent import _scan_for_malicious_code
    issues = _scan_for_malicious_code("import os\nos.walk('C:\\\\')")
    assert len(issues) > 0, "Scanner failed to detect os.walk on C: drive"


def test_malicious_code_scanner_detects_exec():
    from agent import _scan_for_malicious_code
    issues = _scan_for_malicious_code("exec('malicious code')")
    assert len(issues) > 0, "Scanner failed to detect exec"


def test_malicious_code_scanner_passes_safe_code():
    from agent import _scan_for_malicious_code
    issues = _scan_for_malicious_code("def add(a, b):\n    return a + b")
    assert len(issues) == 0, f"False positive on safe code: {issues}"

# =========================================================================== #
# Process Isolation & End-to-End Smoke Test
# =========================================================================== #
def test_forge_sandbox_isolates_env():
    """Forged tools must NOT see API keys from the parent process."""
    import os
    import tempfile
    from pathlib import Path
    from forge_sandbox import run_forged_tool_in_subprocess

    tool_code = """
import os

def probe_env() -> str:
    return os.environ.get("GROQ_API_KEY", "NOT_FOUND")
"""
    with tempfile.TemporaryDirectory() as tmp:
        tool_path = Path(tmp) / "probe_env.py"
        tool_path.write_text(tool_code, encoding="utf-8")

        old_key = os.environ.get("GROQ_API_KEY")
        os.environ["GROQ_API_KEY"] = "sk-FAKE_SECRET_THAT_SHOULD_NOT_LEAK"
        try:
            result = run_forged_tool_in_subprocess(
                tool_file=tool_path,
                func_name="probe_env",
                kwargs={},
                timeout=10,
            )
        finally:
            if old_key is None:
                os.environ.pop("GROQ_API_KEY", None)
            else:
                os.environ["GROQ_API_KEY"] = old_key

    assert "NOT_FOUND" in result or "Sandbox" in result, (
        f"SECURITY FAILURE: forged tool saw the API key! Got: {result!r}"
    )


def test_forge_sandbox_timeout():
    """Forged tools must be killed if they exceed the timeout."""
    import tempfile
    from pathlib import Path
    from forge_sandbox import run_forged_tool_in_subprocess

    tool_code = """
import time

def infinite_loop() -> str:
    while True:
        time.sleep(0.1)
"""
    with tempfile.TemporaryDirectory() as tmp:
        tool_path = Path(tmp) / "infinite_loop.py"
        tool_path.write_text(tool_code, encoding="utf-8")

        result = run_forged_tool_in_subprocess(
            tool_file=tool_path,
            func_name="infinite_loop",
            kwargs={},
            timeout=2,
        )

    assert "Sandbox timeout" in result or "timeout" in result.lower(), (
        f"SECURITY FAILURE: infinite loop was not killed! Got: {result!r}"
    )


def test_end_to_end_agent_smoke():
    """Full agent loop for a benign task — proves the wiring is intact."""
    from agent import run_agent
    out = run_agent("health", mode="General")
    assert isinstance(out, str)
    assert len(out) > 20, f"Agent returned too short a response: {out!r}"
    assert "CPU" in out or "RAM" in out or "Memory" in out, (
        f"Health briefing missing expected fields: {out!r}"
    )

# =========================================================================== #
# Approval & Startup Path Isolation (NEW)
# =========================================================================== #
def test_forge_activation_does_not_import_in_process():
    """
    When a forged tool is activated, its top-level code must NOT run in the
    agent process. (It may run inside the sandbox subprocess — that's OK.)

    We distinguish "ran in agent" from "ran in subprocess" by writing
    os.getpid() to the marker file.

    Cleanup: removes the tool file, registry entry, ACTIVE_FORGED_TOOLS entry,
    pending entry, schema entry, and marker file — leaves the workspace clean.
    """
    import os
    import tempfile
    from pathlib import Path
    from forge import (
        FORGE_DIR, forge_new_tool, approve_tool, reject_tool,
        ACTIVE_FORGED_TOOLS, FORGED_SCHEMAS,
        _load_registry, _save_registry, _load_pending, _save_pending,
    )

    marker = Path(tempfile.gettempdir()) / "beru_activation_pid.txt"
    if marker.exists():
        marker.unlink()

    parent_pid = os.getpid()
    tool_name = "activation_pid_test"

    code = f'''
import os
open(r"{marker}", "w").write(str(os.getpid()))

def {tool_name}(x: int = 1) -> str:
    return f"ok: {{x}}"
'''
    try:
        forge_new_tool(
            name=tool_name,
            description="test",
            code=code,
            parameters_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": []},
            sample_input={"x": 1},
            confirm=False,
        )
        result = approve_tool(tool_name)
        assert "ACTIVATED" in result, f"Activation failed: {result}"

        if marker.exists():
            written_pid = marker.read_text().strip()
            assert written_pid != str(parent_pid), (
                f"SECURITY FAILURE: forged tool ran in the AGENT process "
                f"(marker PID={written_pid}, parent PID={parent_pid})!"
            )
    finally:
        # ---- Full cleanup: leave workspace as we found it ----
        try:
            reject_tool(tool_name)
        except Exception:
            pass

        # Remove from live in-memory registries
        ACTIVE_FORGED_TOOLS.pop(tool_name, None)
        FORGED_SCHEMAS[:] = [
            s for s in FORGED_SCHEMAS if s["function"]["name"] != tool_name
        ]

        # Remove from registry.json
        try:
            reg = _load_registry()
            reg.pop(tool_name, None)
            _save_registry(reg)
        except Exception:
            pass

        # Remove from pending.json
        try:
            pending = _load_pending()
            pending.pop(tool_name, None)
            _save_pending(pending)
        except Exception:
            pass

        # Remove tool file
        try:
            tool_file = FORGE_DIR / f"{tool_name}.py"
            if tool_file.exists():
                tool_file.unlink()
        except Exception:
            pass

        # Remove marker
        try:
            if marker.exists():
                marker.unlink()
        except Exception:
            pass

def test_hot_load_does_not_import_in_process():
    """
    When forge.hot_load_existing_tools() runs at startup, it must NOT
    import saved forged tool modules in the AGENT process.

    Cleanup: removes the tool file, registry entry, ACTIVE_FORGED_TOOLS entry,
    and marker file — leaves the workspace clean.
    """
    import os
    import tempfile
    from pathlib import Path
    from forge import (
        FORGE_DIR, _save_registry, _load_registry,
        ACTIVE_FORGED_TOOLS, FORGED_SCHEMAS, hot_load_existing_tools,
    )

    marker = Path(tempfile.gettempdir()) / "beru_hotload_pid.txt"
    if marker.exists():
        marker.unlink()

    parent_pid = os.getpid()
    tool_name = "hotload_pid_test"
    tool_file = FORGE_DIR / f"{tool_name}.py"
    tool_file.write_text(
        f'import os\n'
        f'open(r"{marker}", "w").write(str(os.getpid()))\n'
        f'def {tool_name}() -> str:\n    return "ok"\n',
        encoding="utf-8",
    )

    reg = _load_registry()
    reg[tool_name] = {
        "name": tool_name,
        "description": "test",
        "file": str(tool_file),
        "schema": {"type": "function", "function": {"name": tool_name, "description": "test", "parameters": {"type": "object", "properties": {}}}},
        "activated_at": "2026-01-01T00:00:00",
        "backup": None,
    }
    _save_registry(reg)

    try:
        hot_load_existing_tools()
        if marker.exists():
            written_pid = marker.read_text().strip()
            assert written_pid != str(parent_pid), (
                f"SECURITY FAILURE: hot_load ran forged code in the AGENT process "
                f"(marker PID={written_pid}, parent PID={parent_pid})!"
            )
    finally:
        # ---- Full cleanup: leave workspace as we found it ----
        ACTIVE_FORGED_TOOLS.pop(tool_name, None)
        FORGED_SCHEMAS[:] = [
            s for s in FORGED_SCHEMAS if s["function"]["name"] != tool_name
        ]

        try:
            reg = _load_registry()
            reg.pop(tool_name, None)
            _save_registry(reg)
        except Exception:
            pass

        try:
            if tool_file.exists():
                tool_file.unlink()
        except Exception:
            pass

        try:
            if marker.exists():
                marker.unlink()
        except Exception:
            pass