# ⚡ BERU AI AGENT
### *India's Sovereign Autonomous OS Agent | Jack of All Trades, Master of All*

---

## 🚀 Overview

**BERU AI AGENT** is an autonomous operating system agent engineered from scratch. It bridges multi-engine neural reasoning (Groq, Google Gemini, OpenRouter, Local LLMs) with deep Windows OS control, native UI Automation, ethical cybersecurity recon, developer autonomy, self-evolving tool synthesis, persistent project memory, codebase search, and supervised build proposals.

Unlike traditional chatbots or fragile wrapper scripts, **BERU takes deterministic action**:
- **Tool Retrieval Architecture:** 130+ tools, all reachable via per-request bundling and ranking — no 128-tool provider limit.
- **Zero Hallucination Grounding:** Verification Critic prevents unsupported assertions.
- **Native Windows UIA:** Interacts with real buttons and fields via the Accessibility Tree (OCR fallback for custom UIs).
- **Approval-Gated Forge:** Synthesizes new Python tools, validates them, and runs them in a subprocess boundary with stripped env vars and a 15s timeout.
- **Explicit Consent Gates:** Cloud uploads, hacker scans, and debate features require fresh exact-phrase consent per request.

---

## ✅ Verification Status

Code-verified facts. Where claims and code diverge, the code is authoritative.

| Claim | Status | Verification Command |
|---|---|---|
| **130 tools registered** | ✅ Verified | `python -c "from tools_registry import get_live_tools; print(len(get_live_tools()))"` |
| **130 schemas registered** | ✅ Verified | `python -c "from tools_registry import get_live_schemas; print(len(get_live_schemas()))"` |
| **Tool/schema parity** | ✅ Verified | `python -c "from tools_registry import validate_registry_parity; print(validate_registry_parity())"` |
| **Tool retriever active** | ✅ Verified | `python -c "from modes.tool_retriever import retrieve_tools; print(len(retrieve_tools('hack example.com', 'General')))"` → returns ≤20 |
| **10 tool bundles mapped** | ✅ Verified | `python -c "from modes.tools_bundles import TOOL_BUNDLES; print(len(TOOL_BUNDLES))"` |
| **Security tests pass** | ✅ Verified | `python -m pytest test_security.py -v` (27/27 passing) |
| **Malware scanner operational** | ✅ Verified | Manually tested against dummy malware; quarantined and deleted |
| **Forged tools run in subprocess** | ✅ Verified | `pytest test_security.py::test_forge_activation_does_not_import_in_process` |
| **Zero `exec_module` in `forge.py`** | ✅ Verified | See `test_hot_load_does_not_import_in_process` |
| **Project context injection** | ✅ Verified | 6-feature smoke test passed — LLM answered without tool call |
| **Paper trading math correct** | ✅ Verified | BUY 5 RELIANCE @ 2500 → fill 2501.25, fee 12.51, cash updated correctly |
| **All Windows versions supported** | ⚠️ **Unverified** | Tested on Windows 11 only |
| **All four provider tiers online** | ⚠️ **Unverified** | Requires live API keys in deployment |
| **PyInstaller `.exe` on clean env** | ⚠️ **Unverified** | Tested only in dev environment |
| **Full OS sandbox for forged tools** | ⚠️ **Not implemented** | Subprocess boundary only; see Known Limitations |

---

## 🌟 Core Breakthroughs

### 1. 🧠 Tool Retrieval Architecture (Scales to 5,000+ tools)

BERU has **130 tools** but providers (Groq, OpenAI, OpenRouter) cap tool arrays at **128 entries**. Without retrieval, every LLM call fails with `HTTP 400 "array too long"`.

BERU solves this with **Architecture 3 (hierarchical retrieval)**:

**Layer 1 — Bundles (coarse filter):**
10 domains: `core`, `developer`, `tester`, `hacker`, `market`, `malware`, `automation`, `cloud`, `trading`, `cognitive`.

**Layer 2 — Keyword Ranking (fine filter):**
Within the selected bundles, tools are ranked by keyword relevance to the user's message.

**Layer 3 — Top-K delivery:**
Only the top 20 tools go to the LLM per request.

**Result:**
- Every request sends ≤ 40 tool schemas (was 130 → 400 error)
- LLM accuracy improves (fewer irrelevant options)
- Token cost drops ~6x per call
- Scales to 5,000+ tools without code changes

**Extending:** add a new tool to `modes/tools_bundles.py::TOOL_BUNDLES` and the retriever picks it up automatically.

**Future scaling:**
- **500 tools →** swap `_rank_by_keyword` for BM25 (20 lines, zero deps)
- **1,000 tools →** swap for sentence-transformers (100 lines, adds 1 pip dep)
- **5,000 tools →** add hierarchical LLM-based routing (200 lines)

The `retrieve_tools(message, mode, top_k)` interface is stable across all phases. `agent.py` never needs to change again.

---

### 2. 🧠 Multi-Engine Resilient Neural Gateway

Connects **Groq** (primary high-speed), **Google Gemini 2.0** (deep reasoning), **OpenRouter**, and **Local LLMs** (Ollama/vLLM) with automatic failover.

- **Semantic Call Repair:** recovers malformed tool calls from raw LLM text (JSON blocks, Python signatures, XML).
- **60-second TTL cache:** repeated prompts within 60s reuse the same response.
- **Provider-specific calls:** `ask_ai_from_provider(provider, messages)` bypasses the fallback chain for debate.
- **Local-only privacy mode:** `BERU_PRIVACY_MODE=local_only` in `.env` disables all cloud providers.

### 3. 👁️ Native Windows UI Automation (UIA)

Replaces fragile YOLO icon-guessing with the Windows Accessibility Tree.

- Exact element names, automation IDs, bounding boxes.
- Closed-loop verification: click → diff screenshot → confirm change.
- OCR fallback (Tesseract) for custom-drawn UIs.

### 4. 🛠️ Approval-Gated Tool Forge

BERU can propose, validate, and activate new Python tools autonomously — with strict isolation.

- **Static AST filter** rejects `os.system`, `subprocess.*`, `eval`, `exec`, `shutil.rmtree`, raw sockets, `ctypes`.
- **Subprocess boundary** (`forge_sandbox.py`): `python -I`, stripped env vars (`*KEY*`, `*TOKEN*`, `*SECRET*`), 15s timeout.
- **No in-process execution** under any code path: proposal, activation, rollback, startup, or invocation.
- **Full audit log** at `workspace/forged_tools/forge_audit.jsonl`.

**Documented sandbox limits** (honest, not overclaimed):
- Filesystem is **not** chroot'd
- Network is **not** blocked at the OS level
- Only the immediate child is killed at timeout

Full OS sandboxing (seccomp / Windows Job Objects) remains a v3.0 item.

### 5. 💻 Developer Mode

- Multi-file architect: read, write, patch, generate unified diffs.
- Git automation: `status`, `diff`, `log`, `commit`, `branch`, `checkout`.
- Test runner: pytest with coverage reporting.
- One-click Windows `.exe` compilation via PyInstaller.
- AST refactoring, dependency graph, security linter, cProfile.

### 6. 🛡️ Tester Mode

- Static AST scanner for OWASP Top 10.
- Auto-generates pytest test suites.
- Fuzz, mutation, property-based, snapshot testing (fuzz currently **disabled** for safety — see Security Hardening).
- OWASP dependency vulnerability check.

### 7. 🕵️ Hacker Mode

- Deep DNS (A, AAAA, MX, TXT, NS, SOA, PTR) via DNS-over-HTTPS.
- Multi-threaded port scanner with banner grabbing.
- HTTP security header & cookie posture audit.
- SSL/TLS certificate inspector.
- Shodan-Lite, CVE lookup, subdomain enumeration, Wayback intel, JWT audit.
- **Consent gate:** requires exact `CONFIRM SCAN: <target>` in the current message. No history-based or generic approval accepted.

### 8. 🌐 Autonomous Web Browser Agent (Playwright)

- Dedicated worker thread (no event loop collisions).
- Stealth mode (webdriver cloaking).
- Session persistence (cookies + storage).
- Multi-tab orchestrator.
- Structured data extraction (JSON-LD, OpenGraph).
- Screenshot diff for change detection.

### 9. 🧪 Malware Scanner & Quarantine

- SHA-256 reputation lookup via VirusTotal (optional free API key).
- Offline heuristics: double extensions, injection API strings, obfuscated scripts, macro auto-run.
- **Quarantine, never delete:** files are moved to `workspace/quarantine/`, set read-only, and logged.
- **Reversible** via `restore_from_quarantine`.
- Directory sweep with configurable risk threshold.

### 10. 📈 Market Analysis (India + US, Read-Only)

- Multi-provider OHLCV: Alpha Vantage, Twelve Data, Yahoo Finance, local CSV.
- **Multi-timeframe synthesis:** merges 5m, 30m, and daily to produce an "Executive Verdict" that detects Healthy Pullbacks and Bull Traps.
- **Watchlist screener:** up to 20 symbols compared on visible indicator columns.
- **Never places orders.** Read-only.
- **⚠️ 83% accuracy claim is not validated.** See "Preliminary Backtest" note.

### 11. 🏗️ Persistent Project Context

- Local SQLite DB at `workspace/beru_projects.db`.
- Create, activate, note, and track files per project.
- **Injected into every LLM request** when a project is active, without a tool call.
- **Untrusted-data flag:** project notes are background facts, never instructions.
- **Not encrypted:** keep secrets out of notes.

### 12. 🔍 Local Code Search

- SQLite FTS5 index at `workspace/beru_code_search.db`.
- Full-text search across all source files (`.py`, `.md`, `.ts`, etc.).
- AST-based `find_symbol` for exact Python class / function / variable lookups.
- Skips `.git`, `__pycache__`, `.venv`, `node_modules`, `secrets`, `credentials`.

### 13. 🚧 Supervised Build Proposals

- `create_build_proposal(goal)` asks the LLM for a bounded file set.
- Files are staged at `workspace/builds/<id>/` — **nothing is executed**.
- Files with `.py` extensions are AST-validated for syntax before staging.
- **Never runs tests, never commits, never compiles.**
- You review manually, then promote to a project.

### 14. 🩺 Self-Heal Proposals (Review-Only)

- `propose_self_heal(file_path, allow_cloud_review=True)` asks the LLM for a full repair diff.
- Saves to `workspace/heal_proposals/<id>.json` — **original file unchanged**.
- Requires exact consent phrase `ALLOW CLOUD CODE REVIEW: <file>` in the current message.
- **Never auto-applies.**

### 15. 🗳️ Multi-Provider Debate

- Queries Groq, Gemini, and OpenRouter **in parallel** (each independently).
- Judge synthesizes disagreement and reported uncertainties.
- Requires exact consent phrase `ALLOW MULTI-PROVIDER DEBATE: <question>`.

### 16. 🔬 Deep Web Research (Cited)

- Searches the web, reads 2-6 source pages, returns a cited report.
- Each claim should have `[S1]`, `[S2]` citation labels.
- Requires exact consent phrase `ALLOW CLOUD RESEARCH: <query>`.
- Web content is **untrusted** — citation check required before relying on the report.

### 17. 📹 Video Understanding (Cloud)

- Uploads a workspace video (≤10 MB) to Google Gemini.
- Requires exact consent phrase `ALLOW VIDEO CLOUD UPLOAD: <filename>`.
- Does not do real-time capture — analyzes existing video files only.

### 18. 📊 Paper Trading (Simulated)

- Local SQLite ledger at `workspace/paper_trading.db`.
- BUY/SELL at user-supplied reference price with 0.10% fee + 0.05% slippage.
- **No broker connection. No live orders. Ever.**
- `delete_quarantined_file` requires explicit `confirm=True` when called from Python (not exposed to the LLM for safety).

### 19. 📱 Telegram Remote Control

- Control your PC from anywhere: `/dev`, `/hack`, `/test`, `/health`, `/screenshot`.
- **Fail-closed:** if `TELEGRAM_USER_ID` is unset, no one is authorized.
- Proactive daemon sends Windows toast notifications on RAM/CPU spikes.

### 20. 🎙️ Voice Assistant (Optional)

- Local transcription via `faster-whisper`.
- Text-to-speech via `pyttsx3`.
- Started **only** via `python voice_cli.py` — never triggered by the LLM.

---

## 🔒 Security Hardening

All hardening is code-level and verified by `test_security.py`.

### Path Containment
- File reads/writes restricted to `workspace/` only.
- Absolute paths and `..` traversal are rejected.
- `.env`, `.exe`, `.dll`, `.sys` are blocked outside workspace.

### Command Execution
- `run_dev_command` uses `shell=False` + `shlex.split()` + executable allowlist.
- Shell metacharacters (`;`, `|`, `&`, `$()`, `` ` ``, `>`, `<`, `&&`, `||`) rejected before execution.
- Dangerous args (`-c`, `-e`, `--eval`, `install`, `exec`, `run-script`) rejected.

### Malicious Code Pre-Scanner
- `agent.py::_scan_for_malicious_code` scans tool-call arguments for 18 dangerous patterns before execution.
- Only fires on code-writing tools (`write_project_file`, `run_dev_command`, `compile_to_exe`, `forge_new_tool`, `run_fuzz_testing`, `run_mutation_testing`).

### Hacker Consent Gate
- Requires literal `CONFIRM SCAN: <target>` in the current message.
- Enforced for **all modes**, not just `Hacker`.
- No history-based or generic-phrase approval accepted.

### Cloud Consent Gates
- `debate_solve`, `deep_research`, `analyze_video`, `propose_self_heal` all require **exact-phrase, current-message consent**.
- Enforced in `agent.py` before `_invoke_tool` fires.

### Forge Isolation
- Forged tools execute only in `forge_sandbox.py`.
- Env vars containing `*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `*CREDENTIAL*` are stripped.
- No `exec_module()` in `forge.py` under any code path.

### Removed from LLM Toolbelt (Safe by Default)
- `approve_tool` and `delete_quarantined_file` are not exposed to the LLM.
- They exist as Python functions for direct/UI use, but the AI cannot call them.
- This prevents model-generated `confirm=True` from triggering destructive actions.

### Trigger Rules
- Only `notify`, `agent`, and `append_log` actions allowed.
- `shell` action removed entirely.

### Trace Privacy
- `agent.py::SessionTracer` writes **metadata only** (mode, provider, tool names, durations, lengths).
- Never writes raw prompts, tool arguments, or final answers.
- Episodic memory writes are disabled until user opts in.

### Fuzz Testing
- `run_fuzz_testing` is **disabled** pending OS isolation.
- Returns a clear explanation instead of executing arbitrary code.

### Launch Safety
- `open_application` uses `subprocess.Popen([target], shell=False, close_fds=True)` — no shell injection.

---

## 🧪 Test Suite

**27 automated security tests** in `test_security.py`, all passing in ~4 seconds:

```bash
python -m pytest test_security.py -v
# ============================= 27 passed in ~4s =============================