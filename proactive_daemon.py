"""
proactive_daemon.py - Proactive Background Guardian & Heartbeat for BERU AI AGENT.
Monitors hardware telemetry, workspace health, and delivers Windows notifications.
"""
import datetime
import os
import sys
import time
import threading
from pathlib import Path
import psutil

from config import WORKSPACE_DIR, HEALTH_CACHE_TTL

_HEALTH_CACHE_LOCK = threading.Lock()
_HEALTH_CACHE_VALUE = ""
_HEALTH_CACHE_TIME = 0.0


def send_notification(title: str, message: str):
    """Dispatches a native Windows Action Center notification."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message[:200],
            app_name="BERU AI AGENT",
            timeout=8,
        )
    except Exception as exc:
        print(f"Notification unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)


def generate_system_health_briefing() -> str:
    """Generates a cached executive briefing of laptop health and workspace status."""
    global _HEALTH_CACHE_VALUE, _HEALTH_CACHE_TIME
    now = time.monotonic()
    with _HEALTH_CACHE_LOCK:
        if _HEALTH_CACHE_VALUE and now - _HEALTH_CACHE_TIME < HEALTH_CACHE_TTL:
            return _HEALTH_CACHE_VALUE
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        disk_root = os.environ.get("SystemDrive", "C:") + "\\" if os.name == "nt" else "/"
        disk = psutil.disk_usage(disk_root)
        boot = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime_hours = int((datetime.datetime.now() - boot).total_seconds() // 3600)

        # Check workspace files
        files = list(WORKSPACE_DIR.glob("*"))
        ws_summary = f"{len(files)} items in workspace"

        briefing = (
            f"🌅 **BERU AI AGENT System Health Briefing**\n"
            f"• **Engineer:** Navneet Jha\n"
            f"• **CPU Utilization:** {cpu}%\n"
            f"• **RAM Memory:** {ram.percent}% used ({ram.used // (1024**3)} GB / {ram.total // (1024**3)} GB)\n"
            f"• **Storage (C: Drive):** {disk.percent}% used ({disk.free / (1024**3):.1f} GB free)\n"
            f"• **System Uptime:** {uptime_hours} hours\n"
            f"• **Workspace Status:** {ws_summary}"
        )
        with _HEALTH_CACHE_LOCK:
            _HEALTH_CACHE_VALUE = briefing
            _HEALTH_CACHE_TIME = time.monotonic()
        return briefing
    except Exception as e:
        return f"Briefing generation error: {e}"


def run_guardian_loop(interval_sec: int = 180):
    """Continuous background monitoring loop."""
    print("🛡️ BERU AI AGENT Guardian Daemon started.")

    # Boot the new features alongside the guardian
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        print(f"Scheduler failed to start: {e}", file=sys.stderr)

    try:
        from watchdog_v2 import start_watchdog, register_callback
        from trigger_rules import handle_event, start_rule_engine

        def _on_watchdog_event(event_type, details):
            handle_event(event_type, details)

        register_callback(_on_watchdog_event)
        start_watchdog(interval_sec=30)
        start_rule_engine(interval_sec=30)
    except Exception as e:
        print(f"Watchdog 2.0 failed to start: {e}", file=sys.stderr)

    last_ram_alert = 0
    while True:
        try:
            ram = psutil.virtual_memory()
            if ram.percent > 90 and (time.time() - last_ram_alert > 600):
                send_notification(
                    "⚠️ High Memory Alert (BERU)",
                    f"System RAM is at {ram.percent}%. Consider closing unused applications."
                )
                last_ram_alert = time.time()
        except Exception:
            pass
        time.sleep(interval_sec)


if __name__ == "__main__":
    run_guardian_loop()
