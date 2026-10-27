"""
trigger_rules.py - Feature 48: Trigger-Action Rules for BERU AI AGENT.

Lets the user (or agent) define natural-language rules:
  "If [condition] then [action]"
  e.g. "If a new file appears in workspace, then summarize its contents"
       "If RAM usage exceeds 90%, then send a notification"
       "If git commit happens, then run the test suite"

Each rule is stored in workspace/rules.json with a condition and an action.
The rule engine checks conditions on each watchdog tick and fires matched actions.
"""
import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import WORKSPACE_DIR

RULES_FILE = WORKSPACE_DIR / "rules.json"
_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
def _load_rules() -> List[Dict[str, Any]]:
    if not RULES_FILE.exists():
        return []
    try:
        data = json.loads(RULES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_rules(items: List[Dict[str, Any]]) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    RULES_FILE.write_text(json.dumps(items, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Condition evaluation
# --------------------------------------------------------------------------- #
def _match_condition(condition_type: str, condition_value: str, event: Dict[str, Any]) -> bool:
    """
    Check whether a fired event satisfies the rule's condition.

    condition_type values:
      - "file_created"       : match any file_created event (optional glob in condition_value)
      - "file_modified"      : match any file_modified event (optional glob)
      - "file_deleted"       : match any file_deleted event
      - "git_commit"         : match any git_commit event
      - "resource_spike"     : match a resource_spike on condition_value (cpu/ram/disk)
      - "cron_tick"          : match the cron tick every N minutes (condition_value = minutes)
    """
    etype = event.get("type", "")
    details = event.get("details", {})

    if condition_type in ("file_created", "file_modified", "file_deleted"):
        if etype != condition_type:
            return False
        if not condition_value.strip():
            return True
        pattern = condition_value.strip()
        return bool(re.search(pattern.replace("*", ".*"), details.get("path", "")))

    if condition_type == "git_commit":
        return etype == "git_commit"

    if condition_type == "resource_spike":
        if etype != "resource_spike":
            return False
        wanted = condition_value.strip().lower()
        if not wanted:
            return True
        return details.get("resource", "").lower() == wanted

    if condition_type == "cron_tick":
        return etype == "cron_tick"

    return False


# --------------------------------------------------------------------------- #
# Action execution
# --------------------------------------------------------------------------- #
def _execute_action(action_type: str, action_value: str, event: Dict[str, Any]) -> str:
    """
    Execute a rule action.

    action_type values:
      - "notify"         : send a Windows notification (action_value = message text)
      - "agent"          : run the agent with the given prompt
      - "shell"          : run a shell command (blocked for dangerous keywords)
      - "append_log"     : append event details to workspace/watchdog_log.jsonl
    """
    if action_type == "notify":
        try:
            from proactive_daemon import send_notification
            msg = action_value or f"Watchdog event: {event.get('type')}"
            send_notification("BERU Trigger Rule", msg)
            return f"notified: {msg}"
        except Exception as e:
            return f"notify failed: {e}"

    if action_type == "agent":
        try:
            from agent import run_agent
            result = run_agent(action_value or "Summarize the latest change")
            return f"agent result: {str(result)[:300]}"
        except Exception as e:
            return f"agent action failed: {e}"

    if action_type == "append_log":
        try:
            log_path = WORKSPACE_DIR / "watchdog_log.jsonl"
            entry = {"ts": time.time(), "rule": action_value or "unnamed", "event": event}
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return f"logged to {log_path.name}"
        except Exception as e:
            return f"append_log failed: {e}"

    return f"unknown action_type '{action_type}'"


# --------------------------------------------------------------------------- #
# Rule engine
# --------------------------------------------------------------------------- #
_engine_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _engine_loop(interval_sec: int = 30) -> None:
    """On every tick, fire rules whose conditions match synthetic cron events."""
    # Fire a periodic cron_tick event for rules that want time-based triggers
    tick_num = 0
    while not _stop_event.is_set():
        try:
            rules = _load_rules()
            tick_num += 1
            synthetic = {"type": "cron_tick", "details": {"tick": tick_num}}
            for rule in rules:
                if rule.get("condition_type") == "cron_tick":
                    # condition_value is expressed in MINUTES; interval_sec is in SECONDS.
                    period_min = int(rule.get("condition_value") or 10)
                    period_ticks = max(1, int((period_min * 60) / max(1, interval_sec)))
                    if tick_num % period_ticks == 0:
                        _execute_action(rule.get("action_type", ""), rule.get("action_value", ""), synthetic)
        except Exception:
            pass
        _stop_event.wait(interval_sec)


def handle_event(event_type: str, details: Dict[str, Any]) -> None:
    """
    Called by the watchdog for every event it detects.
    Matches against all rules and fires the ones that match.
    """
    event = {"type": event_type, "details": details}
    rules = _load_rules()
    for rule in rules:
        try:
            if _match_condition(
                rule.get("condition_type", ""),
                rule.get("condition_value", ""),
                event,
            ):
                result = _execute_action(
                    rule.get("action_type", ""),
                    rule.get("action_value", ""),
                    event,
                )
                # Log the fire (best-effort)
                try:
                    log_path = WORKSPACE_DIR / "rule_fires.jsonl"
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps({
                            "ts": time.time(),
                            "rule_id": rule.get("id"),
                            "event": event_type,
                            "result": str(result)[:300],
                        }) + "\n")
                except Exception:
                    pass
        except Exception:
            continue


# --------------------------------------------------------------------------- #
# Public API (also registered as agent tools)
# --------------------------------------------------------------------------- #
def add_trigger_rule(
    description: str,
    condition_type: str,
    condition_value: str,
    action_type: str,
    action_value: str,
) -> str:
    """
    Add a rule that fires an action when a watchdog event matches.

    condition_type: file_created | file_modified | file_deleted | git_commit | resource_spike | cron_tick
    action_type:    notify | agent | shell | append_log
    """
    valid_c = {"file_created", "file_modified", "file_deleted", "git_commit", "resource_spike", "cron_tick"}
    valid_a = {"notify", "agent", "append_log"}
    if condition_type not in valid_c:
        return f"Failed: condition_type must be one of {sorted(valid_c)}"
    if action_type not in valid_a:
        return f"Failed: action_type must be one of {sorted(valid_a)}"

    rule = {
        "id": uuid.uuid4().hex[:8],
        "description": description.strip(),
        "condition_type": condition_type,
        "condition_value": condition_value,
        "action_type": action_type,
        "action_value": action_value,
        "created_at": time.time(),
    }
    with _lock:
        items = _load_rules()
        items.append(rule)
        _save_rules(items)
    return f"Rule added [{rule['id']}]: {description[:80]}"


def list_trigger_rules() -> str:
    """List all trigger rules."""
    items = _load_rules()
    if not items:
        return "No trigger rules defined."
    lines = [f"Trigger rules ({len(items)}):"]
    for r in items:
        lines.append(
            f"• [{r['id']}] {r.get('description', '(unnamed)')}\n"
            f"    IF {r['condition_type']}={r['condition_value']!r} "
            f"THEN {r['action_type']}={r['action_value'][:40]!r}"
        )
    return "\n".join(lines)


def delete_trigger_rule(rule_id: str) -> str:
    """Remove a rule by ID."""
    rule_id = rule_id.strip()
    with _lock:
        items = _load_rules()
        before = len(items)
        items = [r for r in items if r["id"] != rule_id]
        _save_rules(items)
    if len(items) == before:
        return f"Failed: no rule with ID '{rule_id}'."
    return f"Deleted rule '{rule_id}'."


def start_rule_engine(interval_sec: int = 30) -> str:
    """Start the periodic rule engine (only needed for cron_tick rules)."""
    global _engine_thread
    with _lock:
        if _engine_thread and _engine_thread.is_alive():
            return "Rule engine already running."
        _stop_event.clear()
        _engine_thread = threading.Thread(
            target=_engine_loop, args=(interval_sec,), daemon=True
        )
        _engine_thread.start()
    return f"Rule engine started (interval={interval_sec}s)."


def stop_rule_engine() -> str:
    """Stop the periodic rule engine."""
    global _engine_thread
    _stop_event.set()
    with _lock:
        if _engine_thread:
            _engine_thread.join(timeout=2)
            _engine_thread = None
    return "Rule engine stopped."