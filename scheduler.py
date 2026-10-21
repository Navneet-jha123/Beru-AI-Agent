"""
scheduler.py - Feature 46: Cron-Style Scheduled Tasks for BERU AI AGENT.

Adds:
  - Natural-language task scheduling ("every morning at 8am", "in 5 minutes")
  - Persistent task store (workspace/schedules.json)
  - Background thread that fires due tasks by invoking run_agent()
  - Full CRUD: add, list, cancel, run-now

The scheduler stores tasks as:
  {id, prompt, mode, schedule_type, schedule_value, next_run, last_run, created_at}
"""
import datetime
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import WORKSPACE_DIR

SCHEDULES_FILE = WORKSPACE_DIR / "schedules.json"
_lock = threading.RLock()
_scheduler_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _load_schedules() -> List[Dict[str, Any]]:
    if not SCHEDULES_FILE.exists():
        return []
    try:
        data = json.loads(SCHEDULES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_schedules(items: List[Dict[str, Any]]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULES_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Parsing natural-language schedules to a next_run timestamp
# --------------------------------------------------------------------------- #
def _parse_schedule(schedule_type: str, schedule_value: str, now: Optional[datetime.datetime] = None) -> Optional[float]:
    """
    Returns the next UNIX timestamp at which this schedule should fire, or None if unparseable.

    Supported schedule_type values:
      - "once_in"      : schedule_value = "5m" | "30s" | "2h" | "1d"  -> fires once, then never again
      - "every"        : schedule_value = "5m" | "1h" | "1d"          -> fires every N units
      - "daily_at"     : schedule_value = "08:30"                     -> fires every day at that HH:MM
      - "weekly_on"    : schedule_value = "mon 09:00"                 -> fires weekly
    """
    now = now or datetime.datetime.now()

    if schedule_type == "once_in":
        m = re.fullmatch(r"(\d+)\s*([smhd])", schedule_value.strip().lower())
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2)
        delta = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * n
        return now.timestamp() + delta

    if schedule_type == "every":
        m = re.fullmatch(r"(\d+)\s*([smhd])", schedule_value.strip().lower())
        if not m:
            return None
        n, unit = int(m.group(1)), m.group(2)
        delta = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit] * n
        return now.timestamp() + delta

    if schedule_type == "daily_at":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", schedule_value.strip())
        if not m:
            return None
        hour, minute = int(m.group(1)), int(m.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        return target.timestamp()

    if schedule_type == "weekly_on":
        m = re.fullmatch(r"([a-z]{3})\s+(\d{1,2}):(\d{2})", schedule_value.strip().lower())
        if not m:
            return None
        days = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
        day_name, hour, minute = m.group(1), int(m.group(2)), int(m.group(3))
        if day_name not in days or not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        target_weekday = days[day_name]
        days_ahead = (target_weekday - now.weekday()) % 7
        target = (now + datetime.timedelta(days=days_ahead)).replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if target <= now:
            target += datetime.timedelta(days=7)
        return target.timestamp()

    return None


def _compute_next_after_fire(task: Dict[str, Any]) -> Optional[float]:
    """After a task fires, compute the next fire time. Returns None if the task was one-shot."""
    stype = task.get("schedule_type", "")
    svalue = task.get("schedule_value", "")
    if stype == "once_in":
        return None
    return _parse_schedule(stype, svalue)


# --------------------------------------------------------------------------- #
# Public API (also registered as agent tools)
# --------------------------------------------------------------------------- #
def schedule_task(
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    mode: str = "General",
) -> str:
    """
    Schedule a task to run on a timer.

    schedule_type examples:
      - "once_in"   "5m"          (fire once after 5 minutes)
      - "every"     "1h"          (fire every 1 hour)
      - "daily_at"  "08:30"       (fire every day at 8:30am local time)
      - "weekly_on" "mon 09:00"   (fire every Monday at 9am)

    mode: General / Developer / Tester / Hacker
    """
    schedule_type = schedule_type.strip().lower()
    if schedule_type not in ("once_in", "every", "daily_at", "weekly_on"):
        return (
            "Failed: schedule_type must be one of "
            "'once_in', 'every', 'daily_at', 'weekly_on'."
        )

    next_run = _parse_schedule(schedule_type, schedule_value)
    if next_run is None:
        return (
            f"Failed: could not parse schedule_value '{schedule_value}' "
            f"for schedule_type '{schedule_type}'. "
            f"Examples: '5m', '1h', '2d', '08:30', 'mon 09:00'."
        )

    task = {
        "id": uuid.uuid4().hex[:8],
        "prompt": prompt.strip(),
        "mode": mode.strip().capitalize() or "General",
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "next_run": next_run,
        "last_run": None,
        "created_at": time.time(),
    }

    with _lock:
        items = _load_schedules()
        items.append(task)
        _save_schedules(items)

    _ensure_scheduler_running()
    next_dt = datetime.datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M:%S")
    return f"Scheduled task {task['id']}: '{prompt[:60]}' -> next run at {next_dt}"


def list_scheduled_tasks() -> str:
    """List all scheduled tasks with their next run times."""
    items = _load_schedules()
    if not items:
        return "No scheduled tasks."
    lines = [f"Scheduled tasks ({len(items)}):"]
    for t in items:
        next_dt = datetime.datetime.fromtimestamp(t["next_run"]).strftime("%Y-%m-%d %H:%M:%S") if t.get("next_run") else "—"
        last_dt = (
            datetime.datetime.fromtimestamp(t["last_run"]).strftime("%Y-%m-%d %H:%M:%S")
            if t.get("last_run") else "never"
        )
        lines.append(
            f"• [{t['id']}] ({t.get('mode','General')}) {t['prompt'][:70]}\n"
            f"    schedule: {t['schedule_type']}={t['schedule_value']} "
            f"| next: {next_dt} | last: {last_dt}"
        )
    return "\n".join(lines)


def cancel_scheduled_task(task_id: str) -> str:
    """Cancel a scheduled task by its ID."""
    task_id = task_id.strip()
    with _lock:
        items = _load_schedules()
        before = len(items)
        items = [t for t in items if t["id"] != task_id]
        _save_schedules(items)
    if len(items) == before:
        return f"Failed: no scheduled task with ID '{task_id}'."
    return f"Cancelled scheduled task '{task_id}'."


def run_scheduled_task_now(task_id: str) -> str:
    """Force a scheduled task to fire immediately (does not change its schedule)."""
    task_id = task_id.strip()
    items = _load_schedules()
    task = next((t for t in items if t["id"] == task_id), None)
    if not task:
        return f"Failed: no scheduled task with ID '{task_id}'."
    return _execute_task(task)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #
def _execute_task(task: Dict[str, Any]) -> str:
    """Run one task by invoking the agent. Returns the agent's reply."""
    try:
        from agent import run_agent  # import lazily to avoid circular import
        result = run_agent(task["prompt"], mode=task.get("mode", "General"))
        result_str = str(result)[:4000]
    except Exception as e:
        result_str = f"Scheduled task failed: {type(e).__name__}: {e}"

    # Update task record
    with _lock:
        items = _load_schedules()
        for t in items:
            if t["id"] == task["id"]:
                t["last_run"] = time.time()
                nxt = _compute_next_after_fire(t)
                if nxt is None:
                    # one-shot: remove from store
                    items.remove(t)
                else:
                    t["next_run"] = nxt
                break
        _save_schedules(items)

    return result_str


# --------------------------------------------------------------------------- #
# Background thread
# --------------------------------------------------------------------------- #
def _scheduler_loop():
    """Fire due tasks every 15 seconds."""
    while not _stop_event.is_set():
        try:
            now = time.time()
            due = [t for t in _load_schedules() if t.get("next_run") and t["next_run"] <= now]
            for task in due:
                _execute_task(task)
        except Exception:
            pass
        _stop_event.wait(15)


def _ensure_scheduler_running() -> None:
    """Idempotently start the background thread."""
    global _scheduler_thread
    with _lock:
        if _scheduler_thread is None or not _scheduler_thread.is_alive():
            _stop_event.clear()
            _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
            _scheduler_thread.start()


def start_scheduler() -> str:
    """Public entry point — starts the background thread."""
    _ensure_scheduler_running()
    return "Scheduler thread started."


def stop_scheduler() -> str:
    """Graceful shutdown of the scheduler thread."""
    global _scheduler_thread
    _stop_event.set()
    with _lock:
        if _scheduler_thread:
            _scheduler_thread.join(timeout=2)
            _scheduler_thread = None
    return "Scheduler thread stopped."