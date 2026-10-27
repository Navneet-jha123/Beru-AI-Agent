"""
benchmarks.py - Feature 49: Benchmark Suite for BERU AI AGENT.

Defines 20 fixed benchmark tasks across all modes and runs them end-to-end,
measuring:
  - Wall-clock latency per task
  - Success (agent returned a non-empty answer)
  - Tool usage count
  - Failures (exceptions raised)

Results are appended to workspace/benchmarks/{timestamp}.json. A summary is
returned on each run. This gives a stable regression metric week over week.
"""
import json
import threading
import time
import traceback
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from config import BENCHMARKS_DIR

_lock = threading.RLock()


# --------------------------------------------------------------------------- #
# Benchmark definitions — 20 fixed tasks across all modes
# --------------------------------------------------------------------------- #
BENCHMARK_TASKS: List[Dict[str, Any]] = [
    # ---- General (5) ----
    {"id": "gen_health",     "mode": "General",   "prompt": "health",                                   "expect_tools": ["get_system_health"]},
    {"id": "gen_open_calc",  "mode": "General",   "prompt": "open calculator",                          "expect_tools": ["open_application"]},
    {"id": "gen_search",     "mode": "General",   "prompt": "search google for latest python release",  "expect_tools": ["browser_search"]},
    {"id": "gen_screenshot", "mode": "General",   "prompt": "take a desktop screenshot",                "expect_tools": ["take_desktop_screenshot"]},
    {"id": "gen_episodic",   "mode": "General",   "prompt": "what did we discuss recently",             "expect_tools": ["query_episodic_memory"]},

    # ---- Developer (5) ----
    {"id": "dev_write",      "mode": "Developer", "prompt": "write a hello world python file into workspace/hello.py",  "expect_tools": ["write_project_file"]},
    {"id": "dev_read",       "mode": "Developer", "prompt": "read workspace/hello.py",                  "expect_tools": ["read_project_file"]},
    {"id": "dev_git_status", "mode": "Developer", "prompt": "show git status",                          "expect_tools": ["git_action"]},
    {"id": "dev_run_cmd",    "mode": "Developer", "prompt": "run python --version in the workspace",     "expect_tools": ["run_dev_command"]},
    {"id": "dev_dep_graph",  "mode": "Developer", "prompt": "analyze dependencies of the project",       "expect_tools": ["analyze_dependencies"]},

    # ---- Tester (4) ----
    {"id": "test_audit",     "mode": "Tester",    "prompt": "run a security audit on modes/developer.py", "expect_tools": ["audit_code_security"]},
    {"id": "test_synth",     "mode": "Tester",    "prompt": "synthesize a test suite for modes/hacker.py", "expect_tools": ["synthesize_test_suite"]},
    {"id": "test_owasp",     "mode": "Tester",    "prompt": "check requirements.txt for known vulnerabilities", "expect_tools": ["check_owasp_dependencies"]},
    {"id": "test_snapshot",  "mode": "Tester",    "prompt": "run a snapshot test named benchmark_snapshot with output OK", "expect_tools": ["run_snapshot_test"]},

    # ---- Hacker (4) ----
    {"id": "hack_dns",       "mode": "Hacker",    "prompt": "perform deep DNS recon on example.com",    "expect_tools": ["deep_dns_recon"]},
    {"id": "hack_ssl",       "mode": "Hacker",    "prompt": "inspect SSL certificate for example.com",  "expect_tools": ["inspect_ssl_certificate"]},
    {"id": "hack_headers",   "mode": "Hacker",    "prompt": "audit security headers for example.com",   "expect_tools": ["audit_security_headers"]},
    {"id": "hack_shodan",    "mode": "Hacker",    "prompt": "shodan lite lookup for example.com",       "expect_tools": ["shodan_lite_lookup"]},

    # ---- Meta (2) ----
    {"id": "meta_forge_propose", "mode": "General", "prompt": "propose a tool named bench_tool that returns the string 'benchmark_ok'", "expect_tools": ["forge_new_tool"]},
    {"id": "meta_optimizer",     "mode": "General", "prompt": "show the tool optimizer report",         "expect_tools": ["get_tool_optimizer_report"]},
]


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def _run_one(task: Dict[str, Any]) -> Dict[str, Any]:
    """Run one benchmark task and return a result dict."""
    result: Dict[str, Any] = {
        "id": task["id"],
        "mode": task["mode"],
        "prompt": task["prompt"],
        "started_at": time.time(),
        "duration_sec": 0.0,
        "success": False,
        "answer_len": 0,
        "tools_called": [],
        "expected_tools_missing": [],
        "error": None,
    }

    t0 = time.time()
    try:
        # Import lazily so a broken agent doesn't kill the whole benchmark
        from agent import run_agent
        tools_called: List[str] = []
        tool_failures: List[str] = []

        def _on_tool(name, args):
            tools_called.append(name)

        def _on_result(name, res):
            low = (res or "").lower().lstrip()
            if low.startswith((
                "failed", "tool execution error", "tool typeerror",
                "unknown tool", "browser error",
            )):
                tool_failures.append(f"{name}: {(res or '')[:80]}")

        answer = run_agent(
            task["prompt"],
            mode=task["mode"],
            on_tool_call=_on_tool,
            on_tool_result=_on_result,
        )
        answer_str = str(answer or "").strip()
        result["answer_len"] = len(answer_str)

        low = answer_str.lower()
        is_failure_banner = (
            "all ai providers are currently unavailable" in low
            or low.startswith("ai generation failed")
            or low.startswith("tool execution error")
            or low.startswith("tool typeerror")
            or low.startswith("reached maximum tool execution rounds")
        )

        expected = set(task.get("expect_tools") or [])
        missing = sorted(expected - set(tools_called))
        result["tools_called"] = tools_called
        result["expected_tools_missing"] = missing

        # Success requires: non-empty answer, no failure banner,
        # all expected tools fired, and no tool error surfaced.
        result["success"] = (
            bool(answer_str)
            and not is_failure_banner
            and not missing
            and not tool_failures
        )
        if tool_failures:
            result["tool_failures"] = tool_failures[:5]

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()[:1500]

    result["duration_sec"] = round(time.time() - t0, 2)
    result["finished_at"] = time.time()
    return result


def run_benchmark_suite(subset: Optional[List[str]] = None) -> str:
    """
    Run all 20 benchmark tasks (or a subset by id), persist results, and return a summary.

    Persists to workspace/benchmarks/{timestamp}_{runid}.json.
    """
    tasks = BENCHMARK_TASKS
    if subset:
        wanted = set(subset)
        tasks = [t for t in tasks if t["id"] in wanted]
        if not tasks:
            return f"Failed: none of the requested ids exist. Valid ids: {[t['id'] for t in BENCHMARK_TASKS]}"
        if len(tasks) < 5:
            return (
                f"Failed: minimum 5 benchmark tasks required per run for statistical validity. "
                f"You selected {len(tasks)}: {subset}"
            )

    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex[:8]
    started = time.time()

    results: List[Dict[str, Any]] = []
    for task in tasks:
        r = _run_one(task)
        results.append(r)

    finished = time.time()
    total_sec = round(finished - started, 2)

    success_count = sum(1 for r in results if r["success"])
    failure_count = len(results) - success_count
    missing_tools_total = sum(len(r["expected_tools_missing"]) for r in results)
    avg_duration = round(sum(r["duration_sec"] for r in results) / max(1, len(results)), 2)

    score_pct = round(100.0 * success_count / max(1, len(results)), 1)

    payload = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "total_sec": total_sec,
        "task_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "score_pct": score_pct,
        "avg_duration_sec": avg_duration,
        "missing_expected_tools_total": missing_tools_total,
        "results": results,
    }

    out_path = BENCHMARKS_DIR / f"{payload['timestamp'].replace(':','-')}_{run_id}.json"
    try:
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    lines = [
        f"=== BENCHMARK SUITE [{run_id}] ===",
        f"Tasks: {len(results)}   Success: {success_count}   Failed: {failure_count}",
        f"Score: {score_pct}%   Avg latency: {avg_duration}s   Total: {total_sec}s",
        f"Missing expected tools (total across tasks): {missing_tools_total}",
        f"Saved to: {out_path.name}",
        "",
        "Per-task:",
    ]
    for r in results:
        flag = "OK " if r["success"] else "ERR"
        extra = ""
        if r["expected_tools_missing"]:
            extra = f" | missing: {','.join(r['expected_tools_missing'])}"
        if r["error"]:
            extra += f" | error: {r['error'][:80]}"
        lines.append(f"  [{flag}] {r['id']:22s} {r['duration_sec']:6.2f}s  tools={len(r['tools_called'])}{extra}")

    return "\n".join(lines)


def list_benchmark_tasks() -> str:
    """List all 20 built-in benchmark tasks with their ids."""
    lines = [f"Benchmark tasks ({len(BENCHMARK_TASKS)}):"]
    for t in BENCHMARK_TASKS:
        lines.append(f"  • [{t['id']:22s}] ({t['mode']:9s}) {t['prompt']}")
    return "\n".join(lines)


def latest_benchmark_summary() -> str:
    """Return a summary of the most recent benchmark run."""
    files = sorted(BENCHMARKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return "No benchmark runs recorded yet."
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to read latest benchmark: {e}"
    return (
        f"=== Latest Benchmark: {data.get('timestamp')} ===\n"
        f"Score: {data.get('score_pct')}%   "
        f"Success: {data.get('success_count')}/{data.get('task_count')}   "
        f"Avg: {data.get('avg_duration_sec')}s   "
        f"Total: {data.get('total_sec')}s\n"
        f"File: {files[0].name}"
    )


def compare_with_previous() -> str:
    """Diff the latest benchmark against the run before it — spot regressions."""
    files = sorted(BENCHMARKS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if len(files) < 2:
        return "Need at least two benchmark runs to compare."
    try:
        curr = json.loads(files[0].read_text(encoding="utf-8"))
        prev = json.loads(files[1].read_text(encoding="utf-8"))
    except Exception as e:
        return f"Failed to load benchmark files: {e}"

    curr_map = {r["id"]: r for r in curr.get("results", [])}
    prev_map = {r["id"]: r for r in prev.get("results", [])}

    regressed = []
    improved = []
    for tid, cr in curr_map.items():
        pr = prev_map.get(tid)
        if not pr:
            continue
        if pr["success"] and not cr["success"]:
            regressed.append(tid)
        elif not pr["success"] and cr["success"]:
            improved.append(tid)

    score_delta = round(curr.get("score_pct", 0) - prev.get("score_pct", 0), 1)

    lines = [
        f"=== Benchmark Comparison ===",
        f"Prev: {prev.get('timestamp')}  Score: {prev.get('score_pct')}%",
        f"Curr: {curr.get('timestamp')}  Score: {curr.get('score_pct')}%",
        f"Delta: {score_delta:+.1f} pp",
        "",
        f"Regressed ({len(regressed)}): {', '.join(regressed) if regressed else 'none'}",
        f"Improved  ({len(improved)}): {', '.join(improved) if improved else 'none'}",
    ]
    return "\n".join(lines)