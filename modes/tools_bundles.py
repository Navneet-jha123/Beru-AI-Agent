"""
modes/tools_bundles.py - Tool bundle definitions and keyword-based classifier.

This module is the foundation of BERU's tool-retrieval architecture. Every tool
in tools_registry.BASE_TOOLS belongs to exactly one bundle. At request time,
the classifier picks 1-4 bundles based on the user's message and active mode.
The retriever (modes/tool_retriever.py) then ranks the tools within those
bundles and sends only the top-K to the LLM.

Why bundles: Groq, OpenAI, and OpenRouter cap function-calling tool arrays at
128 entries. BERU currently has 130 tools. Without bundling, every LLM request
fails with HTTP 400 "array too long". Bundling keeps every request at ~20-40
schemas regardless of how many total tools BERU ships with.

Extending: to add a tool, add its name to the appropriate bundle below. To add
a new domain, add a key to TOOL_BUNDLES and a matching keyword list to
_BUNDLE_KEYWORDS.
"""
from __future__ import annotations

from typing import List


# --------------------------------------------------------------------------- #
# Bundle definitions. Every tool name here must exist in tools_registry.BASE_TOOLS.
# --------------------------------------------------------------------------- #
TOOL_BUNDLES = {
    "core": [
        # System health and app control
        "get_system_health", "open_application", "close_application",
        "take_desktop_screenshot", "send_notification",
        # Memory
        "save_fact", "recall_facts", "save_lesson",
        # Screen UIA (basic)
        "inspect_screen", "click_ui_element", "type_on_screen", "press_key",
        # Browser (basic)
        "browser_open", "browser_search", "browser_read",
        "browser_click", "browser_type", "browser_close",
        # Projects
        "create_project", "list_projects", "activate_project",
        "add_project_note", "add_project_file", "get_project_context",
        # Code search
        "index_codebase", "search_code", "find_symbol",
        # Cognitive basics
        "get_tool_optimizer_report", "rate_confidence",
        "query_episodic_memory", "record_episodic_event",
    ],

    "developer": [
        "write_project_file", "read_project_file", "apply_code_patch",
        "run_dev_command", "run_test_suite", "git_action", "compile_to_exe",
        "generate_multi_file_diff", "refactor_ast_rename",
        "analyze_dependencies", "report_test_coverage",
        "resolve_git_conflicts", "generate_pr_description",
        "lint_code_security", "profile_python_script",
        "forge_new_tool", "list_pending_tools", "reject_tool",
        "create_build_proposal", "propose_self_heal",
    ],

    "tester": [
        "audit_code_security", "synthesize_test_suite",
        "run_fuzz_testing", "run_mutation_testing",
        "generate_property_tests", "run_snapshot_test",
        "check_owasp_dependencies",
    ],

    "hacker": [
        "deep_dns_recon", "audit_ports_and_services",
        "audit_security_headers", "inspect_ssl_certificate",
        "shodan_lite_lookup", "lookup_cves_by_service",
        "enumerate_subdomains", "query_wayback_intel",
        "audit_jwt_token", "audit_cookie_posture",
    ],

    "market": [
        "analyze_stock_by_name", "analyze_stock_market",
        "market_data_status", "screen_stock_watchlist",
        "classify_stock_setup", "analyze_intraday_momentum",
        "analyze_30m_swing_momentum", "synthesize_market_verdict",
    ],

    "malware": [
        "check_hash_reputation", "scan_file_for_threats",
        "quarantine_file", "list_quarantine",
        "restore_from_quarantine", "sweep_directory_for_threats",
    ],

    "medical": [
    "parse_lab_report", "parse_lab_text", "calculate_bmi", "calculate_heart_score",
    "calculate_qsofa", "calculate_curb65", "calculate_cha2ds2_vasc", "calculate_wells_pe",
    "calculate_egfr_ckd_epi", "calculate_map", "calculate_anion_gap", "calculate_corrected_calcium",
    "assess_metabolic_risk", "check_symptom_red_flags", "list_calculators",
    "suggest_calculators", "run_calculator", "tool_specs"
    ],
    "reverse_engineering": [
        "hash_file", "analyze_pe_header", "extract_strings", "find_indicators", "disassemble_bytes"
    ],
    # Reserved domain only: no sports data tools exist in this repository yet.
        "sports": [
        "fetch_football_standings", "fetch_team_form", "fetch_cricket_score", "fetch_nba_standings",
        "calculate_elo_probability", "calculate_win_percentage", "calculate_points_per_game",
        "calculate_expected_goals", "calculate_form_index",
        "suggest_sports_tools", "run_sports_tool", "list_sports_tools",
    ],

    "automation": [
        "schedule_task", "list_scheduled_tasks",
        "cancel_scheduled_task", "run_scheduled_task_now",
        "start_watchdog", "stop_watchdog", "watchdog_status",
        "add_watch_folder", "remove_watch_folder", "list_watch_folders",
        "add_trigger_rule", "list_trigger_rules", "delete_trigger_rule",
        "run_benchmark_suite", "list_benchmark_tasks",
        "latest_benchmark_summary", "compare_with_previous",
    ],

    "cloud": [
        "debate_solve", "deep_research", "analyze_video",
        "save_browser_session", "load_browser_session",
        "orchestrate_multi_tabs", "extract_structured_data",
        "diff_page_snapshots",
    ],

    "trading": [
        "place_paper_order", "get_paper_portfolio",
    ],

    "cognitive": [
        "tree_of_thought_solve", "chain_of_verification",
        "counterfactual_evaluate", "adversarial_critique",
        "decompose_task_recursive", "detect_goal_drift",
        "update_preference", "get_user_preferences",
        "estimate_cognitive_load", "add_entity_relation",
        "query_entity_graph", "suggest_failure_recovery",
    ],
}


# --------------------------------------------------------------------------- #
# Keyword map. If a message contains any of these words (case-insensitive,
# whole-word match), that bundle is included. Keep this tight — too many
# keywords cause bundles to always load, defeating the purpose.
# --------------------------------------------------------------------------- #
_BUNDLE_KEYWORDS = {
    "developer": [
        "code", "python", "script", "function", "file", "write", "read",
        "patch", "compile", "exe", "build", "git", "commit", "branch",
        "refactor", "rename", "diff", "pr", "pull request", "heal", "fix",
        "bug", "workspace", "workspace file", "exe file",
    ],
    "tester": [
        "test", "pytest", "coverage", "fuzz", "mutation", "snapshot",
        "owasp", "vulnerability scan", "audit code", "property test",
    ],
    "hacker": [
        "hack", "recon", "scan", "port", "dns", "ssl", "tls", "certificate",
        "subdomain", "shodan", "cve", "wayback", "jwt", "cookie", "header",
        "osint", "enumerate", "vulnerability",
    ],
    "market": [
        "stock", "market", "ticker", "symbol", "price", "chart", "candle",
        "reliance", "tcs", "infy", "nifty", "sensex", "nasdaq", "nyse",
        "aapl", "tsla", "msft", "rsi", "sma", "macd", "atr", "vwap",
        "momentum", "swing", "intraday", "daily", "1d", "5m", "30m",
        "portfolio analysis", "analyze stock", "stock setup",
    ],
    "trading": [
        "buy", "sell", "trade", "paper trade", "paper", "order", "fill",
        "position", "portfolio", "cash", "shares", "quantity",
    ],
    "malware": [
        "malware", "virus", "quarantine", "scan file", "hash", "virustotal",
        "threat", "suspicious", "eicar", "sweep directory", "downloads",
    ],
    "automation": [
        "schedule", "cron", "every", "daily", "watchdog", "watch folder",
        "trigger", "rule", "benchmark", "recurring", "every hour",
        "every day", "every morning",
    ],
    "cloud": [
        "debate", "multi-provider", "compare providers", "second opinion",
        "research", "deep research", "web research", "analyze video",
        "video", "self-heal proposal", "cloud review",
    ],
    "cognitive": [
        "think deeply", "tree of thought", "analyze deeply", "verify",
        "counterfactual", "adversarial", "critique", "goal drift",
        "decompose", "preference", "entity", "knowledge graph",
    ],
    "medical": [
    "medical", "lab report", "blood test", "hemoglobin", "cholesterol", "bmi",
    "symptoms", "chest pain", "sepsis", "heart score", "ecg", "troponin",
    "metabolic", "diabetes", "hypertension", "qsofa", "pneumonia", "curb-65",
    "atrial fibrillation", "afib", "stroke", "pulmonary embolism", "pe",
    "kidney", "renal", "creatinine", "egfr", "blood pressure", "map",
    "anion gap", "acidosis", "calcium", "albumin", "calculator"
    ],
    "reverse_engineering": [
        "reverse engineering", "disassemble", "disassembly", "pe header", "binary analysis",
        "extract strings", "malware sample", "dll imports", "hash", "md5", "sha256",
        "entropy", "ioc", "indicators", "url", "registry key"
    ],
        "sports": [
        "sports", "score", "match", "football", "soccer", "cricket", "nba",
        "basketball", "premier league", "la liga", "standings", "table",
        "elo", "win probability", "win rate", "form", "recent results",
        "xg", "expected goals", "points per game", "ppg", "league",
        "athlete", "team", "tournament", "ipl", "world cup", "test match"
    ],
    
}


def _tokenize(text: str) -> set:
    """Return lowercase word tokens for keyword matching."""
    import re
    return set(re.findall(r"[a-z][a-z0-9_]+", (text or "").lower()))


def classify_bundles(user_message: str, mode: str = "General") -> List[str]:
    """
    Pick 1-4 bundles based on mode + message keywords.

    - 'core' is ALWAYS included (system health, memory, project, code search).
    - The active mode adds its bundle automatically.
    - Keyword matches add more bundles.
    - Safety fallback: if classification seems uncertain, include 'developer'
      as a broad fallback so the LLM isn't starved of tool choices.
    """
    bundles = {"core"}
    mode_key = (mode or "General").strip().lower()

    if mode_key == "developer":
        bundles.add("developer")
    elif mode_key == "tester":
        bundles.add("tester")
    elif mode_key == "hacker":
        bundles.add("hacker")
    elif mode_key == "medical":
        bundles.add("medical")
    elif mode_key == "reverse engineering":
        bundles.add("reverse_engineering")

    tokens = _tokenize(user_message)
    raw_lower = (user_message or "").lower()

    for bundle, keywords in _BUNDLE_KEYWORDS.items():
        for kw in keywords:
            # Handle multi-word keywords by substring match, single-word by token.
            if " " in kw:
                if kw in raw_lower:
                    bundles.add(bundle)
                    break
            elif kw in tokens:
                bundles.add(bundle)
                break

    return sorted(bundles)


def bundles_for_tool(tool_name: str) -> List[str]:
    """Return which bundles contain a given tool name."""
    return [b for b, names in TOOL_BUNDLES.items() if tool_name in names]


def all_tool_names() -> List[str]:
    """Return every tool name declared in any bundle."""
    seen = []
    for names in TOOL_BUNDLES.values():
        seen.extend(names)
    return seen