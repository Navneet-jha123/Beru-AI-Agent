"""
tools_registry.py - Master Tool Registry for BERU AI AGENT.
Aggregates OS controls, UIA vision, Developer, Tester, Hacker, Browser, and Forged tools.
"""
import datetime
import os
import subprocess
import time
from typing import Any, Callable, Dict, List

import psutil

from brain import (
    recall_facts, save_fact, save_lesson,
    record_episodic_event, query_episodic_memory,
    add_entity_relation, query_entity_graph,
    rate_confidence, update_preference, get_user_preferences,
    estimate_cognitive_load, tree_of_thought_solve,
    chain_of_verification, counterfactual_evaluate,
    adversarial_critique, record_tool_outcome,
    get_tool_optimizer_report, suggest_failure_recovery,
    detect_goal_drift, decompose_task_recursive,
)
from browser_agent import (
    browser_click, browser_close, browser_open,
    browser_read, browser_search, browser_type,
    save_browser_session, load_browser_session,
    orchestrate_multi_tabs, extract_structured_data,
    diff_page_snapshots,
)
from forge import (
    ACTIVE_FORGED_TOOLS, FORGED_SCHEMAS, forge_new_tool, hot_load_existing_tools,
    approve_tool, reject_tool, list_pending_tools, rollback_tool,
)
from modes.developer import (
    apply_code_patch, compile_to_exe, git_action,
    read_project_file, run_dev_command, run_test_suite,
    write_project_file, generate_multi_file_diff,
    refactor_ast_rename, analyze_dependencies,
    report_test_coverage, resolve_git_conflicts,
    generate_pr_description, lint_code_security,
    profile_python_script,
)
from modes.hacker import (
    audit_ports_and_services, audit_security_headers,
    deep_dns_recon, inspect_ssl_certificate,
    shodan_lite_lookup, lookup_cves_by_service,
    enumerate_subdomains, query_wayback_intel,
    audit_jwt_token, audit_cookie_posture,
)
from modes.tester import (
    audit_code_security, synthesize_test_suite,
    run_fuzz_testing, run_mutation_testing,
    generate_property_tests, run_snapshot_test,
    check_owasp_dependencies,
)
from proactive_daemon import generate_system_health_briefing, send_notification
from scheduler import (
    schedule_task, list_scheduled_tasks, cancel_scheduled_task, run_scheduled_task_now,
)
from watchdog_v2 import (
    start_watchdog, stop_watchdog, watchdog_status,
    add_watch_folder, remove_watch_folder, list_watch_folders,
)
from trigger_rules import (
    add_trigger_rule, list_trigger_rules, delete_trigger_rule,
)
from benchmarks import (
    run_benchmark_suite, list_benchmark_tasks,
    latest_benchmark_summary, compare_with_previous,
)
from vision_uia import (
    capture_screenshot, click_element_by_name,
    inspect_screen, press_keyboard_key, type_into_field,
    switch_app_context, get_active_app_context,
    record_desktop_activity, click_element_with_verification,
    auto_fill_form, detect_screen_hotspots,
)


# --------------------------------------------------------------------------- #
# Core OS Helpers
# --------------------------------------------------------------------------- #
APP_MAP = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "terminal": "wt.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "chrome": "chrome.exe",
    "edge": "msedge.exe",
    "vscode": "code",
}

def open_application(app_name: str) -> str:
    """Launches an application by name (e.g. notepad, chrome, paint, calculator, vscode)."""
    name = app_name.lower().strip()
    target = APP_MAP.get(name, name)
    try:
        subprocess.Popen(target, shell=True)
        time.sleep(0.5)
        return f"Successfully opened '{app_name}'."
    except Exception as e:
        return f"Failed to open '{app_name}': {e}"


def close_application(app_name: str) -> str:
    """Closes running processes matching app_name."""
    name = app_name.lower().strip().replace(".exe", "")
    protected = {"explorer", "svchost", "system", "csrss", "winlogon", "services"}
    if name in protected:
        return f"Refused: '{app_name}' is a protected Windows core process."

    terminated = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and name in proc.info["name"].lower():
                proc.terminate()
                terminated.append(proc.info["name"])
        except Exception:
            continue
    if terminated:
        return f"Closed {len(terminated)} instance(s) of '{app_name}'."
    return f"No running application found matching '{app_name}'."


def take_desktop_screenshot(filename: str = "screenshot.png") -> str:
    """Captures the current full desktop screen and saves it."""
    from config import WORKSPACE_DIR
    out_path = WORKSPACE_DIR / filename
    try:
        capture_screenshot(str(out_path))
        return f"Desktop screenshot captured and saved to '{out_path}'."
    except Exception as e:
        return f"Failed to take screenshot: {e}"


# --------------------------------------------------------------------------- #
# Unified Tool Map & Schemas
# --------------------------------------------------------------------------- #
hot_load_existing_tools()

BASE_TOOLS: Dict[str, Callable] = {
    # System
    "get_system_health": generate_system_health_briefing,
    "open_application": open_application,
    "close_application": close_application,
    "take_desktop_screenshot": take_desktop_screenshot,
    "send_notification": send_notification,
    # Memory
    "save_fact": save_fact,
    "recall_facts": recall_facts,
    "save_lesson": save_lesson,
    # Vision & Screen UIA
    "inspect_screen": inspect_screen,
    "click_ui_element": click_element_by_name,
    "type_on_screen": type_into_field,
    "press_key": press_keyboard_key,
    # Developer Mode
    "write_project_file": write_project_file,
    "read_project_file": read_project_file,
    "apply_code_patch": apply_code_patch,
    "run_dev_command": run_dev_command,
    "run_test_suite": run_test_suite,
    "git_action": git_action,
    "compile_to_exe": compile_to_exe,
    # Tester Mode
    "audit_code_security": audit_code_security,
    "synthesize_test_suite": synthesize_test_suite,
    # Hacker Mode
    "deep_dns_recon": deep_dns_recon,
    "audit_ports_and_services": audit_ports_and_services,
    "audit_security_headers": audit_security_headers,
    "inspect_ssl_certificate": inspect_ssl_certificate,
    # Autonomous Browser Agent
    "browser_open": browser_open,
    "browser_search": browser_search,
    "browser_read": browser_read,
    "browser_click": browser_click,
    "browser_type": browser_type,
    "browser_close": browser_close,
    # Self-Evolving Forge
    "forge_new_tool": forge_new_tool,
    "approve_tool": approve_tool,
    "reject_tool": reject_tool,
    "list_pending_tools": list_pending_tools,
    "rollback_tool": rollback_tool,
        # Feature 46: Scheduled tasks
    "schedule_task": schedule_task,
    "list_scheduled_tasks": list_scheduled_tasks,
    "cancel_scheduled_task": cancel_scheduled_task,
    "run_scheduled_task_now": run_scheduled_task_now,
    # Feature 47: Watchdog 2.0
    "start_watchdog": start_watchdog,
    "stop_watchdog": stop_watchdog,
    "watchdog_status": watchdog_status,
    "add_watch_folder": add_watch_folder,
    "remove_watch_folder": remove_watch_folder,
    "list_watch_folders": list_watch_folders,
    # Feature 48: Trigger-action rules
    "add_trigger_rule": add_trigger_rule,
    "list_trigger_rules": list_trigger_rules,
    "delete_trigger_rule": delete_trigger_rule,
    # Feature 49: Benchmarks
    "run_benchmark_suite": run_benchmark_suite,
    "list_benchmark_tasks": list_benchmark_tasks,
    "latest_benchmark_summary": latest_benchmark_summary,
    "compare_with_previous": compare_with_previous,
    # Cognitive & Memory (features 1-8, 13-16)
    "record_episodic_event": record_episodic_event,
    "query_episodic_memory": query_episodic_memory,
    "add_entity_relation": add_entity_relation,
    "query_entity_graph": query_entity_graph,
    "rate_confidence": rate_confidence,
    "update_preference": update_preference,
    "get_user_preferences": get_user_preferences,
    "estimate_cognitive_load": estimate_cognitive_load,
    "decompose_task_recursive": decompose_task_recursive,
    "get_tool_optimizer_report": get_tool_optimizer_report,
    "suggest_failure_recovery": suggest_failure_recovery,
    "detect_goal_drift": detect_goal_drift,
    # Reasoning (features 9-12)
    "tree_of_thought_solve": tree_of_thought_solve,
    "chain_of_verification": chain_of_verification,
    "counterfactual_evaluate": counterfactual_evaluate,
    "adversarial_critique": adversarial_critique,
    # Developer mode extras (features 17-24)
    "generate_multi_file_diff": generate_multi_file_diff,
    "refactor_ast_rename": refactor_ast_rename,
    "analyze_dependencies": analyze_dependencies,
    "report_test_coverage": report_test_coverage,
    "resolve_git_conflicts": resolve_git_conflicts,
    "generate_pr_description": generate_pr_description,
    "lint_code_security": lint_code_security,
    "profile_python_script": profile_python_script,
    # Tester mode extras (features 25-29)
    "run_fuzz_testing": run_fuzz_testing,
    "run_mutation_testing": run_mutation_testing,
    "generate_property_tests": generate_property_tests,
    "run_snapshot_test": run_snapshot_test,
    "check_owasp_dependencies": check_owasp_dependencies,
    # Hacker mode extras (features 30-35)
    "shodan_lite_lookup": shodan_lite_lookup,
    "lookup_cves_by_service": lookup_cves_by_service,
    "enumerate_subdomains": enumerate_subdomains,
    "query_wayback_intel": query_wayback_intel,
    "audit_jwt_token": audit_jwt_token,
    "audit_cookie_posture": audit_cookie_posture,
    # Browser extras (features 42-45)
    "save_browser_session": save_browser_session,
    "load_browser_session": load_browser_session,
    "orchestrate_multi_tabs": orchestrate_multi_tabs,
    "extract_structured_data": extract_structured_data,
    "diff_page_snapshots": diff_page_snapshots,
    # Vision/UIA extras (features 36-40)
    "switch_app_context": switch_app_context,
    "get_active_app_context": get_active_app_context,
    "record_desktop_activity": record_desktop_activity,
    "click_element_with_verification": click_element_with_verification,
    "auto_fill_form": auto_fill_form,
    "detect_screen_hotspots": detect_screen_hotspots,
}

BASE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {"type": "function", "function": {"name": "get_system_health", "description": "Fetches real-time CPU, RAM, Disk, Uptime, and workspace status briefing.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "open_application", "description": "Launches a Windows application by name (e.g. notepad, calc, chrome, paint).", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "close_application", "description": "Terminates a running application by name.", "parameters": {"type": "object", "properties": {"app_name": {"type": "string"}}, "required": ["app_name"]}}},
    {"type": "function", "function": {"name": "take_desktop_screenshot", "description": "Takes a full resolution screenshot of the desktop.", "parameters": {"type": "object", "properties": {"filename": {"type": "string", "default": "screenshot.png"}}, "required": []}}},
    {"type": "function", "function": {"name": "send_notification", "description": "Sends a native Windows popup notification.", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}}, "required": ["title", "message"]}}},

    {"type": "function", "function": {"name": "save_fact", "description": "Saves a permanent fact into long-term memory.", "parameters": {"type": "object", "properties": {"fact": {"type": "string"}, "category": {"type": "string", "default": "general"}}, "required": ["fact"]}}},
    {"type": "function", "function": {"name": "recall_facts", "description": "Recalls saved facts from long-term memory.", "parameters": {"type": "object", "properties": {"query": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "save_lesson", "description": "Saves a permanent lesson learned from a task outcome.", "parameters": {"type": "object", "properties": {"topic": {"type": "string"}, "lesson": {"type": "string"}, "source_task": {"type": "string", "default": ""}}, "required": ["topic", "lesson"]}}},

    {"type": "function", "function": {"name": "inspect_screen", "description": "Inspects active window and returns exact UI elements (buttons, inputs, menus) via Windows UI Automation.", "parameters": {"type": "object", "properties": {"window_keyword": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "click_ui_element", "description": "Clicks an on-screen button, tab, or menu item by visible text or label.", "parameters": {"type": "object", "properties": {"target_name": {"type": "string"}, "double_click": {"type": "boolean", "default": False}}, "required": ["target_name"]}}},
    {"type": "function", "function": {"name": "type_on_screen", "description": "Types text into the currently focused window or field.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "submit": {"type": "boolean", "default": False}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "press_key", "description": "Presses a keyboard key (e.g. 'enter', 'tab', 'esc', 'win').", "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}}},

    {"type": "function", "function": {"name": "write_project_file", "description": "Writes or overwrites a file in the workspace.", "parameters": {"type": "object", "properties": {"rel_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["rel_path", "content"]}}},
    {"type": "function", "function": {"name": "read_project_file", "description": "Reads file lines from the workspace.", "parameters": {"type": "object", "properties": {"rel_path": {"type": "string"}, "start_line": {"type": "integer", "default": 1}, "end_line": {"type": "integer", "default": 0}}, "required": ["rel_path"]}}},
    {"type": "function", "function": {"name": "apply_code_patch", "description": "Replaces a specific block of code in a file.", "parameters": {"type": "object", "properties": {"rel_path": {"type": "string"}, "target_block": {"type": "string"}, "replacement_block": {"type": "string"}}, "required": ["rel_path", "target_block", "replacement_block"]}}},
    {"type": "function", "function": {"name": "run_dev_command", "description": "Executes shell commands (pytest, git, python, npm) in the workspace safely.", "parameters": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer", "default": 60}}, "required": ["command"]}}},
    {"type": "function", "function": {"name": "run_test_suite", "description": "Executes pytest on the workspace test suite.", "parameters": {"type": "object", "properties": {"test_target": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "git_action", "description": "Performs Git actions: status, diff, log, commit, branch, checkout.", "parameters": {"type": "object", "properties": {"action": {"type": "string"}, "message": {"type": "string", "default": ""}, "branch": {"type": "string", "default": ""}}, "required": ["action"]}}},
    {"type": "function", "function": {"name": "compile_to_exe", "description": "Compiles a Python script into a standalone Windows .exe using PyInstaller.", "parameters": {"type": "object", "properties": {"script_rel_path": {"type": "string"}, "onefile": {"type": "boolean", "default": True}, "noconsole": {"type": "boolean", "default": True}}, "required": ["script_rel_path"]}}},

    {"type": "function", "function": {"name": "audit_code_security", "description": "Performs static AST security and quality audit on Python code for OWASP Top 10 vulnerabilities.", "parameters": {"type": "object", "properties": {"rel_path": {"type": "string"}}, "required": ["rel_path"]}}},
    {"type": "function", "function": {"name": "synthesize_test_suite", "description": "Generates a full pytest test suite for all functions and classes in a Python file.", "parameters": {"type": "object", "properties": {"source_rel_path": {"type": "string"}}, "required": ["source_rel_path"]}}},

    {"type": "function", "function": {"name": "deep_dns_recon", "description": "Performs deep DNS enumeration (A, AAAA, MX, TXT, NS, PTR) for a domain or IP.", "parameters": {"type": "object", "properties": {"domain_or_ip": {"type": "string"}}, "required": ["domain_or_ip"]}}},
    {"type": "function", "function": {"name": "audit_ports_and_services", "description": "Scans common network ports and grabs service version banners.", "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "audit_security_headers", "description": "Inspects HTTP response headers (CSP, HSTS, X-Frame-Options, CORS, Cookies).", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "inspect_ssl_certificate", "description": "Inspects SSL/TLS certificates, expiry dates, cipher strength, and SANs.", "parameters": {"type": "object", "properties": {"hostname": {"type": "string"}}, "required": ["hostname"]}}},

    {"type": "function", "function": {"name": "browser_open", "description": "Navigates to a webpage in the browser.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "browser_search", "description": "Fast instant web search returning top results and summaries.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "browser_read", "description": "Extracts clean readable text from the current webpage.", "parameters": {"type": "object", "properties": {"max_chars": {"type": "integer", "default": 3500}}, "required": []}}},
    {"type": "function", "function": {"name": "browser_click", "description": "Clicks an element in the browser by selector or text.", "parameters": {"type": "object", "properties": {"selector": {"type": "string", "default": ""}, "text": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "browser_type", "description": "Types text into a browser input field.", "parameters": {"type": "object", "properties": {"text": {"type": "string"}, "selector": {"type": "string", "default": "input"}, "submit": {"type": "boolean", "default": False}}, "required": ["text"]}}},
    {"type": "function", "function": {"name": "browser_close", "description": "Closes the browser session.", "parameters": {"type": "object", "properties": {}, "required": []}}},

    {"type": "function", "function": {"name": "forge_new_tool", "description": "Proposes a new Python tool. Requires approval via approve_tool unless confirm=True. Never pass confirm=True unless the user has explicitly authorized immediate activation.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "description": {"type": "string"}, "code": {"type": "string"}, "parameters_schema": {"type": "object"}, "sample_input": {"type": "object"}, "confirm": {"type": "boolean", "default": False}}, "required": ["name", "description", "code", "parameters_schema"]}}},
    {"type": "function", "function": {"name": "query_episodic_memory", "description": "Queries past conversation history. Use for 'What did we discuss yesterday?' or topic lookups.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "date_filter": {"type": "string", "default": ""}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "add_entity_relation", "description": "Links entities in the knowledge graph (e.g. person --[works_on]--> project).", "parameters": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}, "relation": {"type": "string"}, "entity_type": {"type": "string", "default": "concept"}}, "required": ["source", "target", "relation"]}}},
    {"type": "function", "function": {"name": "query_entity_graph", "description": "Finds related entities in the knowledge graph.", "parameters": {"type": "object", "properties": {"entity_name": {"type": "string"}}, "required": ["entity_name"]}}},
    {"type": "function", "function": {"name": "estimate_cognitive_load", "description": "Estimates tool count needed for a task; warns if >5.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]}}},
    {"type": "function", "function": {"name": "get_tool_optimizer_report", "description": "Shows tool success/failure statistics.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "suggest_failure_recovery", "description": "Provides a fallback decision tree for a failed tool.", "parameters": {"type": "object", "properties": {"tool_name": {"type": "string"}, "error_message": {"type": "string"}}, "required": ["tool_name", "error_message"]}}},
    {"type": "function", "function": {"name": "tree_of_thought_solve", "description": "Generates 3 alternative strategies for a hard problem and picks the best.", "parameters": {"type": "object", "properties": {"problem": {"type": "string"}}, "required": ["problem"]}}},
    {"type": "function", "function": {"name": "chain_of_verification", "description": "Verifies a draft answer against tool evidence.", "parameters": {"type": "object", "properties": {"draft_answer": {"type": "string"}}, "required": ["draft_answer"]}}},
    {"type": "function", "function": {"name": "adversarial_critique", "description": "Ruthless red-team critique of an answer.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}, "prompt": {"type": "string"}}, "required": ["answer", "prompt"]}}},
    {"type": "function", "function": {"name": "generate_multi_file_diff", "description": "Shows unified diff for multi-file edits before applying.", "parameters": {"type": "object", "properties": {"file_changes": {"type": "object"}}, "required": ["file_changes"]}}},
    {"type": "function", "function": {"name": "refactor_ast_rename", "description": "Safely renames a symbol via AST.", "parameters": {"type": "object", "properties": {"file_rel_path": {"type": "string"}, "old_name": {"type": "string"}, "new_name": {"type": "string"}}, "required": ["file_rel_path", "old_name", "new_name"]}}},
    {"type": "function", "function": {"name": "analyze_dependencies", "description": "Finds circular imports and module dependencies.", "parameters": {"type": "object", "properties": {"folder_path": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "report_test_coverage", "description": "Reports test coverage percentage.", "parameters": {"type": "object", "properties": {"test_target": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "generate_pr_description", "description": "Generates a PR description from git diff and log.", "parameters": {"type": "object", "properties": {"branch_name": {"type": "string", "default": "main"}}, "required": []}}},
    {"type": "function", "function": {"name": "lint_code_security", "description": "Bandit-style security lint on Python files.", "parameters": {"type": "object", "properties": {"file_or_dir": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "profile_python_script", "description": "Runs cProfile on a script; shows top 10 slowest functions.", "parameters": {"type": "object", "properties": {"script_path": {"type": "string"}}, "required": ["script_path"]}}},
    {"type": "function", "function": {"name": "run_fuzz_testing", "description": "Runs 100 extreme fuzz inputs against a function.", "parameters": {"type": "object", "properties": {"function_code_or_file": {"type": "string"}, "iterations": {"type": "integer", "default": 100}}, "required": ["function_code_or_file"]}}},
    {"type": "function", "function": {"name": "run_mutation_testing", "description": "Mutates operators to verify test suite catches bugs.", "parameters": {"type": "object", "properties": {"file_rel_path": {"type": "string"}, "test_file_rel_path": {"type": "string", "default": ""}}, "required": ["file_rel_path"]}}},
    {"type": "function", "function": {"name": "generate_property_tests", "description": "Generates Hypothesis-style property tests.", "parameters": {"type": "object", "properties": {"file_rel_path": {"type": "string"}}, "required": ["file_rel_path"]}}},
    {"type": "function", "function": {"name": "run_snapshot_test", "description": "Compares output against a saved snapshot.", "parameters": {"type": "object", "properties": {"test_name": {"type": "string"}, "actual_output": {"type": "string"}, "update_snapshot": {"type": "boolean", "default": False}}, "required": ["test_name", "actual_output"]}}},
    {"type": "function", "function": {"name": "check_owasp_dependencies", "description": "Scans requirements.txt for known vulnerable packages.", "parameters": {"type": "object", "properties": {"req_file_path": {"type": "string", "default": "requirements.txt"}}, "required": []}}},
    {"type": "function", "function": {"name": "shodan_lite_lookup", "description": "Queries Shodan InternetDB (free) for exposed services and CVEs.", "parameters": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}}},
    {"type": "function", "function": {"name": "lookup_cves_by_service", "description": "Looks up CVEs for a service name + version.", "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}, "version": {"type": "string", "default": ""}}, "required": ["service_name"]}}},
    {"type": "function", "function": {"name": "enumerate_subdomains", "description": "Discovers subdomains via CT logs + wordlist.", "parameters": {"type": "object", "properties": {"domain": {"type": "string"}}, "required": ["domain"]}}},
    {"type": "function", "function": {"name": "query_wayback_intel", "description": "Finds archived URLs, forgotten APIs, config leaks.", "parameters": {"type": "object", "properties": {"domain": {"type": "string"}, "limit": {"type": "integer", "default": 40}}, "required": ["domain"]}}},
    {"type": "function", "function": {"name": "audit_jwt_token", "description": "Decodes and audits a JWT for alg=none, weak HMAC, missing exp.", "parameters": {"type": "object", "properties": {"token": {"type": "string"}}, "required": ["token"]}}},
    {"type": "function", "function": {"name": "audit_cookie_posture", "description": "Audits Set-Cookie for SameSite, Secure, HttpOnly.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "save_browser_session", "description": "Persists browser cookies/storage to disk.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "load_browser_session", "description": "Restores browser cookies/storage from disk.", "parameters": {"type": "object", "properties": {"filepath": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "orchestrate_multi_tabs", "description": "Opens up to 5 URLs in parallel tabs to compare data.", "parameters": {"type": "object", "properties": {"urls": {"type": "array", "items": {"type": "string"}}, "max_tabs": {"type": "integer", "default": 5}}, "required": ["urls"]}}},
    {"type": "function", "function": {"name": "extract_structured_data", "description": "Extracts JSON-LD, OpenGraph, microdata from a page.", "parameters": {"type": "object", "properties": {"url": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "diff_page_snapshots", "description": "Compares current page against a saved baseline; reports visual delta.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "snapshot_id": {"type": "string", "default": "default"}}, "required": ["url"]}}},
    {"type": "function", "function": {"name": "switch_app_context", "description": "Brings a window matching the keyword to the foreground.", "parameters": {"type": "object", "properties": {"window_title_keyword": {"type": "string"}}, "required": ["window_title_keyword"]}}},
    {"type": "function", "function": {"name": "get_active_app_context", "description": "Returns the title and process of the currently focused window.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "record_desktop_activity", "description": "Records desktop activity as GIF for N seconds.", "parameters": {"type": "object", "properties": {"duration_sec": {"type": "integer", "default": 5}, "output_filename": {"type": "string", "default": "desktop_recording.gif"}}, "required": []}}},
    {"type": "function", "function": {"name": "click_element_with_verification", "description": "Clicks an element and verifies the UI changed via screenshot diff.", "parameters": {"type": "object", "properties": {"target_name": {"type": "string"}, "expected_change_hint": {"type": "string", "default": ""}}, "required": ["target_name"]}}},
    {"type": "function", "function": {"name": "auto_fill_form", "description": "Fills on-screen form fields by matching labels. Input is JSON dict of field→value.", "parameters": {"type": "object", "properties": {"field_mappings_json": {"type": "string"}}, "required": ["field_mappings_json"]}}},
    {"type": "function", "function": {"name": "detect_screen_hotspots", "description": "Finds unresponsive UI controls via hover-diff detection.", "parameters": {"type": "object", "properties": {"window_title": {"type": "string", "default": ""}}, "required": []}}},
    {"type": "function", "function": {"name": "record_episodic_event", "description": "Saves a completed session to episodic memory for future recall.", "parameters": {"type": "object", "properties": {"session_id": {"type": "string"}, "prompt": {"type": "string"}, "final_answer": {"type": "string"}, "mode": {"type": "string", "default": "General"}}, "required": ["session_id", "prompt", "final_answer"]}}},
    {"type": "function", "function": {"name": "rate_confidence", "description": "Rates confidence (1-10) of a proposed answer against tool evidence.", "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}}},
    {"type": "function", "function": {"name": "update_preference", "description": "Stores a learned user preference key/value.", "parameters": {"type": "object", "properties": {"pref_key": {"type": "string"}, "pref_value": {"type": "string"}}, "required": ["pref_key", "pref_value"]}}},
    {"type": "function", "function": {"name": "get_user_preferences", "description": "Retrieves all stored user preferences.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "decompose_task_recursive", "description": "Recursively decomposes a complex task into hierarchical subtasks up to depth 3.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "depth": {"type": "integer", "default": 1}, "max_depth": {"type": "integer", "default": 3}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "counterfactual_evaluate", "description": "Compares two alternative approaches on speed, reliability, and error risk.", "parameters": {"type": "object", "properties": {"approach_a": {"type": "string"}, "approach_b": {"type": "string"}, "context": {"type": "string"}}, "required": ["approach_a", "approach_b", "context"]}}},
    {"type": "function", "function": {"name": "detect_goal_drift", "description": "Checks if the current agent action has drifted from the original goal.", "parameters": {"type": "object", "properties": {"original_goal": {"type": "string"}, "current_action": {"type": "string"}}, "required": ["original_goal", "current_action"]}}},
    {"type": "function", "function": {"name": "resolve_git_conflicts", "description": "Resolves Git merge conflict markers using 'ours', 'theirs', or 'both' strategy.", "parameters": {"type": "object", "properties": {"file_rel_path": {"type": "string"}, "strategy": {"type": "string", "default": "theirs"}}, "required": ["file_rel_path"]}}},
    {"type": "function", "function": {"name": "approve_tool", "description": "Activates a previously proposed forged tool after user approval.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "reject_tool", "description": "Rejects and discards a pending forged tool proposal.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {"name": "list_pending_tools", "description": "Lists forged tools waiting for approval.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "rollback_tool", "description": "Deactivates a live forged tool and restores its last backup.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
     # Feature 46
    {"type": "function", "function": {"name": "schedule_task", "description": "Schedule a task to run on a timer. schedule_type: once_in/every/daily_at/weekly_on. Examples: once_in '5m', every '1h', daily_at '08:30', weekly_on 'mon 09:00'.", "parameters": {"type": "object", "properties": {"prompt": {"type": "string"}, "schedule_type": {"type": "string"}, "schedule_value": {"type": "string"}, "mode": {"type": "string", "default": "General"}}, "required": ["prompt", "schedule_type", "schedule_value"]}}},
    {"type": "function", "function": {"name": "list_scheduled_tasks", "description": "List all scheduled tasks.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "cancel_scheduled_task", "description": "Cancel a scheduled task by ID.", "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}}},
    {"type": "function", "function": {"name": "run_scheduled_task_now", "description": "Force a scheduled task to fire immediately.", "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"]}}},

    # Feature 47
    {"type": "function", "function": {"name": "start_watchdog", "description": "Start Watchdog 2.0 background monitoring (files, git, resources).", "parameters": {"type": "object", "properties": {"interval_sec": {"type": "integer", "default": 30}}, "required": []}}},
    {"type": "function", "function": {"name": "stop_watchdog", "description": "Stop Watchdog 2.0.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "watchdog_status", "description": "Show Watchdog 2.0 state.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "add_watch_folder", "description": "Add a folder to the watch list.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "remove_watch_folder", "description": "Stop watching a folder.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "list_watch_folders", "description": "List watched folders.", "parameters": {"type": "object", "properties": {}, "required": []}}},

    # Feature 48
    {"type": "function", "function": {"name": "add_trigger_rule", "description": "Add a trigger-action rule. condition_type: file_created/file_modified/file_deleted/git_commit/resource_spike/cron_tick. action_type: notify/agent/shell/append_log.", "parameters": {"type": "object", "properties": {"description": {"type": "string"}, "condition_type": {"type": "string"}, "condition_value": {"type": "string"}, "action_type": {"type": "string"}, "action_value": {"type": "string"}}, "required": ["description", "condition_type", "condition_value", "action_type", "action_value"]}}},
    {"type": "function", "function": {"name": "list_trigger_rules", "description": "List all trigger rules.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "delete_trigger_rule", "description": "Delete a trigger rule by ID.", "parameters": {"type": "object", "properties": {"rule_id": {"type": "string"}}, "required": ["rule_id"]}}},

    # Feature 49
    {"type": "function", "function": {"name": "run_benchmark_suite", "description": "Run the 20-task benchmark suite (or a subset by id). Saves results to workspace/benchmarks/.", "parameters": {"type": "object", "properties": {"subset": {"type": "array", "items": {"type": "string"}}}, "required": []}}},
    {"type": "function", "function": {"name": "list_benchmark_tasks", "description": "List all 20 built-in benchmark tasks.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "latest_benchmark_summary", "description": "Show the most recent benchmark run summary.", "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {"name": "compare_with_previous", "description": "Diff the latest benchmark against the previous one to spot regressions.", "parameters": {"type": "object", "properties": {}, "required": []}}},
]


def get_live_tools() -> Dict[str, Callable]:
    """Returns all base tools merged with live forged tools."""
    combined = dict(BASE_TOOLS)
    combined.update(ACTIVE_FORGED_TOOLS)
    return combined


def get_live_schemas() -> List[Dict[str, Any]]:
    """Returns all tool schemas merged with dynamic forged schemas."""
    return list(BASE_TOOL_SCHEMAS) + list(FORGED_SCHEMAS)

def validate_registry_parity() -> str:
    """Reports any base tools that lack a matching schema, and vice versa."""
    tool_names = set(BASE_TOOLS)
    schema_names = {s["function"]["name"] for s in BASE_TOOL_SCHEMAS}
    missing = sorted(tool_names - schema_names)
    orphan = sorted(schema_names - tool_names)
    lines = []
    if missing:
        lines.append(f"Tools without schemas ({len(missing)}): {missing}")
    if orphan:
        lines.append(f"Schemas without tools ({len(orphan)}): {orphan}")
    if not lines:
        return f"Registry parity OK: {len(tool_names)} tools, {len(schema_names)} schemas."
    return "\n".join(lines)