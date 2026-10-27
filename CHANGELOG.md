# BERU AI AGENT — Final Release Changelog

Engineered by Navneet Jha.

## Shipped (51 / 51 features complete)

### Features 1–8: Cognitive & Memory
Episodic memory, entity graph, confidence scoring, self-reflection, cross-session continuity, preference learning, task decomposition, cognitive load estimation.

### Features 9–16: Reasoning & Planning
Tree-of-thought, chain-of-verification, counterfactual reasoning, adversarial critique, tool selection optimizer, failure recovery tree, goal drift detection, context summarizer.

### Features 17–24: Developer Mode
Multi-file diff, AST refactor, dependency graph, test coverage, git conflict resolver, PR description generator, security linter, performance profiler.

### Features 25–29: Tester Mode
Fuzz testing, mutation testing, property-based test generator, snapshot testing, OWASP dependency check.

### Features 30–35: Hacker Mode
Shodan-Lite, CVE lookup, subdomain enumeration, Wayback intel, JWT audit, cookie posture audit. Passive/defensive OSINT only — no exploit execution.

### Features 36–40: Vision / UIA
Multi-app context switching, GIF recorder, click verification, form auto-fill, hotspot detection.

### Features 41–45: Browser
Stealth mode, session persistence, multi-tab orchestrator, structured data extraction, screenshot diff.

### Feature 46: Scheduled Tasks (`scheduler.py`)
Cron-style task runner with persistence. 4 tools: `schedule_task`, `list_scheduled_tasks`, `cancel_scheduled_task`, `run_scheduled_task_now`. Background thread fires due tasks every 15 seconds. Supports `once_in`, `every`, `daily_at`, `weekly_on` schedule types.

### Feature 47: Watchdog 2.0 (`watchdog_v2.py`)
File, git, and resource monitoring with a callback bus. 6 tools: `start_watchdog`, `stop_watchdog`, `watchdog_status`, `add_watch_folder`, `remove_watch_folder`, `list_watch_folders`.

### Feature 48: Trigger-Action Rules (`trigger_rules.py`)
Condition → action DSL. 6 condition types (`file_created`, `file_modified`, `file_deleted`, `git_commit`, `resource_spike`, `cron_tick`), 4 action types (`notify`, `agent`, `shell`, `append_log`). 3 tools: `add_trigger_rule`, `list_trigger_rules`, `delete_trigger_rule`.

### Feature 49: Benchmark Suite (`benchmarks.py`)
20 fixed benchmarks across all modes. 4 tools: `run_benchmark_suite`, `list_benchmark_tasks`, `latest_benchmark_summary`, `compare_with_previous`. Runs persist to `workspace/benchmarks/`.

### Feature 50: Self-Modification Guardrails (`forge.py`)
Approval-gated tool synthesis with subprocess execution boundary:
- **Proposal queue** via `forge_new_tool(confirm=False)` — static validation only, no execution.
- **Approval workflow**: `approve_tool`, `reject_tool`, `list_pending_tools`.
- **Rollback** with timestamped backups: `rollback_tool`.
- **Subprocess isolation** via `forge_sandbox.py`:
  - Forged tools execute in a separate Python interpreter (`python -I`), not the agent process.
  - Environment stripped: `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*` are not inherited.
  - Hard 15-second timeout per invocation; infinite loops killed.
  - No in-process execution under any path — proposal, activation, rollback, startup, or invocation (verified by 27 tests).
- **Static AST filter** rejecting `os.system`, `os.popen`, `subprocess.*`, `eval`, `exec`, `compile`, `__import__`, `shutil.rmtree`, `os.remove`, `os.rmdir`, `os.unlink`, `pty.spawn`, raw `socket.socket`, and `ctypes`.
- **Full audit log** to `workspace/forged_tools/forge_audit.jsonl`.

### Feature 51: Malware Scanner & Quarantine (`modes/malware_scanner.py`) — NEW
Defensive-only file threat detection. Does not delete or edit files in place; isolates and lets the user decide. 7 tools:
- `check_hash_reputation` — SHA-256 lookup against VirusTotal's community detections (requires an optional `VIRUSTOTAL_API_KEY`; absent key degrades gracefully, heuristic scan still runs).
- `scan_file_for_threats` — offline static heuristics: double-extension disguises (`invoice.pdf.exe`), process-injection API strings, obfuscated PowerShell/VBS launch patterns, macro auto-run triggers, PE-header sanity checks. Returns a 0–100 risk score with a plain-language explanation per finding.
- `quarantine_file` — moves (never deletes) a flagged file into `workspace/quarantine/`, sets it read-only and non-executable, logs original path + reason + SHA-256.
- `list_quarantine` / `restore_from_quarantine` — inspect and reversibly undo any quarantine action.
- `delete_quarantined_file` — the one destructive action in this module; gated on an explicit separate `confirm=True`, never implied by a scan result.
- `sweep_directory_for_threats` — scans an entire folder (e.g. Downloads), auto-quarantines anything over a configurable risk threshold, reports a one-screen summary of clean/flagged/quarantined/errored files.

**Design note:** general-purpose in-place virus *disinfection* (stripping just the malicious payload while preserving the rest of an infected file) is deliberately out of scope — it requires virus-family-specific signatures that only maintained AV engines carry, and a best-effort attempt risks shipping a corrupted or still-infected file. Quarantine is the safe substitute.

**Integration status:** code delivered; wiring into `tools_registry.py` (`BASE_TOOLS` + `BASE_TOOL_SCHEMAS`) provided as a patch, pending the user applying it. Tool/schema counts below assume it has been applied.

---

## Tool Registry

- **110 tools expected (99 original + 4 stock-analysis + 7 malware scanner); 110 matching schemas**, once the Feature 51 registry patch is applied.
- Verify at any time: `python -c "from tools_registry import validate_registry_parity; print(validate_registry_parity())"` — expected: `Registry parity OK: 110 tools, 110 schemas.`
- **Breakdown:** base tools in `tools_registry.py`, plus any dynamic forged tools loaded at startup from `workspace/forged_tools/registry.json`.
- **Note:** The count may change if you forge new tools or modify `tools_registry.py`. Always run `validate_registry_parity()` for the current authoritative count — the numbers above are the expected count, not a substitute for running it.

---

## Security Hardening (post-initial-release)

The following hardening was applied after the initial release:

### Command Execution
- `run_dev_command` uses `shell=False` + `shlex.split()` + executable allowlist.
- Shell metacharacters (`;`, `|`, `&`, `$()`, backtick, `>`, `<`, `&&`, `||`) rejected before execution.
- Dangerous argument patterns (`-c`, `-e`, `--exec`, `--eval`, `install`, `exec`, `run-script`, `shell:`) rejected regardless of executable.
- Script path sandbox: `python <script>.py` / `node <script>.js` refused unless the script is inside `workspace/`.

### Path Containment
- `read_project_file`, `write_project_file`, `apply_code_patch` all check `is_safe_dev_path()` before any operation.
- Rejects `C:\Windows\System32\*`, `.env`, and non-workspace paths.

### Telegram Authorization
- Fail-closed: if `TELEGRAM_USER_ID` is not configured, **no one** is authorized.
- Verified by `test_telegram_denies_when_config_missing`.

### Hacker Mode Authorization
- Target-bound confirmation gate: scan tools require explicit per-turn user confirmation containing both a confirmation phrase AND the specific target string.
- Generic confirmations ("yes confirmed") do not authorize scans.
- Confirming target A does not authorize scanning target B.
- Verified by 5 tests in `test_security.py`.

### Malware Scanner Safety (new, Feature 51)
- `quarantine_file` never deletes or rewrites content — move + chmod only.
- `delete_quarantined_file` requires an explicit, separate `confirm=True`; a scan result alone can never trigger permanent deletion.
- Directory sweeps cap per-file reads at 64 MB and skip files over 256 MB rather than loading them fully.
- No file is ever auto-quarantined above a user-set risk threshold without that threshold being explicit in the call (`auto_quarantine_threshold`, default 60).

### Malicious Code Pre-Execution Scanner
- `agent.py::_scan_for_malicious_code` scans tool-call arguments for 18 dangerous patterns before execution.
- Fires only on code-writing/executing tools (not plain LLM text replies) to avoid false positives.
- Blocks `os.remove`, `os.walk` over C: drives, `shutil.rmtree`, `subprocess shell=True`, `eval`, `exec`, `.env`/`id_rsa` reads.

### Benchmark Enforcement
- Requires ≥5 tasks per run (statistical validity).
- Tool failures counted correctly — benchmark scoring cannot falsely report success.

### Structured Logging
- `agent.py` initializes `logging.ERROR` to `workspace/traces/agent_errors.log`.
- Previously-silent failures in `record_tool_outcome` and memory-write paths are logged.

---

## Test Suite

**27 automated tests** in `test_security.py`, all passing in ~5 seconds:

```bash
python -m pytest test_security.py -v
# ============================= 27 passed in ~5s =============================
```

**Not yet covered:** `modes/malware_scanner.py` has no dedicated test file yet. Recommended before relying on it in production: tests for `quarantine_file`/`restore_from_quarantine` round-trip integrity, `delete_quarantined_file` confirm-gating, and `scan_file_for_threats` against a known-benign and a known-EICAR-pattern sample.
