"""Guarded Windows service restart helper."""
from __future__ import annotations

import os
import re
import subprocess
import time
from typing import Any

import psutil


def get_top_processes(limit: int = 10) -> str:
    """Return a bounded local CPU/memory snapshot without terminating processes."""
    limit = max(1, min(int(limit), 25))
    processes = []
    for proc in psutil.process_iter(attrs=["pid", "name", "memory_info"]):
        try:
            proc.cpu_percent(interval=None)
            processes.append(proc)
        except (psutil.Error, OSError):
            continue
    time.sleep(0.25)
    rows: list[dict[str, Any]] = []
    for proc in processes:
        try:
            cpu = proc.cpu_percent(interval=None)
            memory = proc.info.get("memory_info")
            rows.append({"pid": proc.info["pid"], "name": proc.info.get("name") or "unknown",
                         "cpu_percent": round(cpu, 1),
                         "memory_mb": round(memory.rss / (1024 * 1024), 1) if memory else None})
        except (psutil.Error, OSError, KeyError):
            continue
    rows.sort(key=lambda row: (-row["cpu_percent"], -(row["memory_mb"] or 0), row["pid"]))
    return "Top processes (read-only snapshot; CPU sample window 0.25s):\n" + "\n".join(
        f"PID {row['pid']} · {row['name']} · CPU {row['cpu_percent']}% · RAM {row['memory_mb']} MB"
        for row in rows[:limit]
    )


def restart_service(service_name: str) -> str:
    """Restart one exact service name explicitly allowlisted by the operator."""
    if os.name != "nt":
        return "Service restart is supported only on Windows."
    name = (service_name or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", name):
        return "Rejected: invalid Windows service name."
    allowed = {part.strip().casefold() for part in os.getenv("BERU_RESTARTABLE_SERVICES", "").split(",") if part.strip()}
    if name.casefold() not in allowed:
        return "Rejected: service is not allowlisted. Set BERU_RESTARTABLE_SERVICES to exact service names after review."
    try:
        query = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True, timeout=10, check=False)
        if query.returncode != 0:
            return f"Service query failed: {query.stderr.strip() or query.stdout.strip()[:300]}"
        if "STOPPED" not in query.stdout.upper():
            stop = subprocess.run(["sc.exe", "stop", name], capture_output=True, text=True, timeout=15, check=False)
            if stop.returncode != 0 and "not started" not in (stop.stdout + stop.stderr).lower():
                return f"Service stop failed: {(stop.stderr or stop.stdout).strip()[:300]}"
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                state = subprocess.run(["sc.exe", "query", name], capture_output=True, text=True, timeout=8, check=False)
                if "STOPPED" in state.stdout.upper():
                    break
                time.sleep(1)
            else:
                return "Service did not stop within 20 seconds; start was not attempted."
        start = subprocess.run(["sc.exe", "start", name], capture_output=True, text=True, timeout=15, check=False)
        if start.returncode != 0:
            return f"Service stopped but could not be restarted: {(start.stderr or start.stdout).strip()[:300]}"
        return f"Restart requested for allowlisted service '{name}'."
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Service restart failed safely: {type(exc).__name__}: {exc}"
