"""
watchdog_v2.py - Feature 47: Watchdog 2.0 for BERU AI AGENT.

Monitors more than just RAM:
  - File changes in workspace/ (with configurable debounce)
  - Git commits in the project (via git log polling)
  - System resource spikes (CPU/RAM/disk)
  - User-defined folder watch list

Each trigger fires a registered callback — the daemon in proactive_daemon.py
installs one that dispatches native Windows notifications.
"""
import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from config import WORKSPACE_DIR, BASE_DIR

_lock = threading.RLock()
_stop_event = threading.Event()
_monitor_thread: Optional[threading.Thread] = None

# Registered callbacks: each receives (event_type, details_dict)
_callbacks: List[Callable[[str, Dict[str, Any]], None]] = []

# File snapshot: path_str -> (mtime, size)
_file_snapshot: Dict[str, tuple] = {}

# Git snapshot: latest commit hash
_last_git_commit: Optional[str] = None

# Watched folders (in addition to workspace)
_watched_folders: Set[Path] = {WORKSPACE_DIR}
_resource_high_since: Dict[str, float] = {}
_resource_alerted: Set[str] = set()


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def register_callback(fn: Callable[[str, Dict[str, Any]], None]) -> None:
    """Register a callback that fires when any watchdog event occurs."""
    with _lock:
        if fn not in _callbacks:
            _callbacks.append(fn)


def add_watch_folder(path: str) -> str:
    """Watch an additional folder for file changes."""
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        return f"Failed: '{path}' is not a directory."
    with _lock:
        _watched_folders.add(p)
    return f"Now watching: {p}"


def remove_watch_folder(path: str) -> str:
    """Stop watching a folder."""
    p = Path(path).expanduser().resolve()
    with _lock:
        if p in _watched_folders:
            _watched_folders.discard(p)
            return f"Stopped watching: {p}"
    return f"Not watching '{path}'."


def list_watch_folders() -> str:
    """List all folders currently being watched."""
    with _lock:
        if not _watched_folders:
            return "No folders are being watched."
        lines = [f"Watching {len(_watched_folders)} folders:"]
        for p in _watched_folders:
            lines.append(f"  • {p}")
        return "\n".join(lines)


def watchdog_status() -> str:
    """Return current watchdog state."""
    running = _monitor_thread is not None and _monitor_thread.is_alive()
    with _lock:
        return (
            f"Watchdog 2.0: {'RUNNING' if running else 'STOPPED'}\n"
            f"  Watching folders: {len(_watched_folders)}\n"
            f"  Tracked files:    {len(_file_snapshot)}\n"
            f"  Git commit:       {_last_git_commit or 'not checked yet'}\n"
            f"  Registered callbacks: {len(_callbacks)}"
        )


def start_watchdog(interval_sec: int = 30) -> str:
    """Start the background monitoring thread."""
    global _monitor_thread
    with _lock:
        if _monitor_thread and _monitor_thread.is_alive():
            return "Watchdog already running."
        _stop_event.clear()
        _monitor_thread = threading.Thread(
            target=_monitor_loop, args=(interval_sec,), daemon=True
        )
        _monitor_thread.start()
    return f"Watchdog 2.0 started (interval={interval_sec}s)."


def stop_watchdog() -> str:
    """Stop the background monitoring thread."""
    global _monitor_thread
    _stop_event.set()
    with _lock:
        if _monitor_thread:
            _monitor_thread.join(timeout=2)
            _monitor_thread = None
    return "Watchdog 2.0 stopped."


# --------------------------------------------------------------------------- #
# Monitoring internals
# --------------------------------------------------------------------------- #
def _emit(event_type: str, details: Dict[str, Any]) -> None:
    """Invoke all registered callbacks with the event."""
    with _lock:
        cbs = list(_callbacks)
    for cb in cbs:
        try:
            cb(event_type, details)
        except Exception:
            pass


def _scan_files() -> Dict[str, tuple]:
    """Return {path_str: (mtime, size)} for all watched folders."""
    result: Dict[str, tuple] = {}
    with _lock:
        folders = list(_watched_folders)
    for folder in folders:
        if not folder.exists():
            continue
        try:
            for p in folder.rglob("*"):
                if not p.is_file():
                    continue
                # Skip large binary/venv-style dirs to keep scan fast
                if any(part in (".git", "__pycache__", "node_modules", "venv", ".venv", "build", "dist")
                       for part in p.parts):
                    continue
                try:
                    st = p.stat()
                    result[str(p)] = (st.st_mtime, st.st_size)
                except Exception:
                    continue
        except Exception:
            continue
    return result


def _detect_file_changes() -> None:
    global _file_snapshot
    current = _scan_files()
    with _lock:
        old = dict(_file_snapshot)
        _file_snapshot = current

    created = set(current) - set(old)
    deleted = set(old) - set(current)
    modified = {
        k for k in (set(current) & set(old))
        if current[k][0] != old[k][0] or current[k][1] != old[k][1]
    }

    for path in created:
        _emit("file_created", {"path": path})
    for path in deleted:
        _emit("file_deleted", {"path": path})
    for path in modified:
        _emit("file_modified", {"path": path})


def _get_latest_git_commit() -> Optional[str]:
    """Return the latest short SHA if BASE_DIR is a git repo, else None."""
    if not (BASE_DIR / ".git").exists():
        return None
    try:
        res = subprocess.run(
            ["git", "log", "-n", "1", "--format=%h %s"],
            cwd=str(BASE_DIR),
            capture_output=True, text=True, timeout=5,
        )
        if res.returncode == 0:
            return res.stdout.strip() or None
    except Exception:
        pass
    return None


def _detect_git_change() -> None:
    global _last_git_commit
    latest = _get_latest_git_commit()
    if latest is None:
        return
    with _lock:
        prev = _last_git_commit
        _last_git_commit = latest
    if prev is not None and prev != latest:
        _emit("git_commit", {"previous": prev, "current": latest})


def _detect_resource_spike() -> None:
    """Emit one resource event only after the configured threshold persists 5 minutes."""
    try:
        import psutil
        ram = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/")
        values = {"cpu": (float(cpu), 90.0), "ram": (float(ram.percent), 90.0),
                  "disk": (float(disk.percent), 95.0)}
        now = time.monotonic()
        with _lock:
            for resource, (value, threshold) in values.items():
                if value >= threshold:
                    _resource_high_since.setdefault(resource, now)
                    duration = now - _resource_high_since[resource]
                    if duration >= 300 and resource not in _resource_alerted:
                        _resource_alerted.add(resource)
                        _emit("resource_spike", {"resource": resource, "value": value,
                                                 "duration_sec": int(duration), "threshold": threshold})
                else:
                    _resource_high_since.pop(resource, None)
                    _resource_alerted.discard(resource)
    except Exception:
        pass


def _monitor_loop(interval_sec: int) -> None:
    """Main scan loop."""
    # Initial snapshot
    _detect_file_changes()
    _detect_git_change()

    while not _stop_event.is_set():
        try:
            _detect_file_changes()
            _detect_git_change()
            _detect_resource_spike()
        except Exception:
            pass
        _stop_event.wait(interval_sec)
