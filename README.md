# ⚡ BERU AI AGENT
### *India's Sovereign Autonomous OS Agent | Jack of All Trades, Master of All*

[![BERU Security Tests](https://github.com/Navneet-jha123/Beru-AI-Agent/actions/workflows/test.yml/badge.svg)](https://github.com/Navneet-jha123/Beru-AI-Agent/actions/workflows/test.yml)
---

## 🚀 Overview

**BERU AI AGENT** is a state-of-the-art autonomous operating system agent engineered from scratch. It bridges cutting-edge multi-engine neural reasoning (Groq, Google Gemini 2.0, OpenRouter, and Local LLMs) with deep Windows operating system control, native UI Automation (UIA), ethical cybersecurity reconnaissance, developer autonomy, and an unshackled self-evolving tool forge.

Unlike traditional chatbots or fragile wrapper scripts, **BERU AI AGENT** takes deterministic action:
- **Zero Hallucination Grounding:** Verification Critic prevents unsupported assertions.
- **Native Windows UI Automation (UIA):** Interacts with buttons, menus, and text fields via the Windows Accessibility Tree, avoiding OCR for standard controls (with OCR fallback for custom-drawn UIs).
- **Subprocess-Sandboxed Tool Forge:** Synthesizes, smoke-tests, debugs, and executes new Python tools in an isolated subprocess without rebooting.
- **High-Limit Specialized Modes:** Developer, Tester, Hacker, and General modes operating at peak capacity.

---

## ✅ Verification Status

This project distinguishes between **code-verified facts** and **documentation claims**. Where they diverge, the code is authoritative.

| Claim | Status | Verification Command |
|---|---|---|
| 99 tools registered | ✅ Verified | `python -c "from tools_registry import get_live_tools; print(len(get_live_tools()))"` |
| 99 schemas registered | ✅ Verified | `python -c "from tools_registry import get_live_schemas; print(len(get_live_schemas()))"` |
| Tool/schema parity | ✅ Verified | `python -c "from tools_registry import validate_registry_parity; print(validate_registry_parity())"` |
| Security tests pass | ✅ Verified | `python -m pytest test_security.py -v` (27/27 passing) |
| Forged tools run in subprocess | ✅ Verified | `pytest test_security.py::test_forge_activation_does_not_import_in_process` |
| Zero `exec_module` in `forge.py` | ✅ Verified | `python -c "import ast; tree = ast.parse(open('forge.py',encoding='utf-8').read()); print(sum(1 for n in ast.walk(tree) if isinstance(n,ast.Call) and getattr(n.func,'attr','')=='exec_module'))"` |
| Test suite is idempotent | ✅ Verified | Registry count is byte-identical before and after running tests |
| All Windows versions supported | ⚠️ **Unverified** | Tested on Windows 11 only |
| All four provider tiers online | ⚠️ **Unverified** | Requires live API keys in deployment environment |
| PyInstaller `.exe` on clean environment | ⚠️ **Unverified** | Tested only in dev environment |
| 5-minute soak test under load | ⚠️ **Unverified** | Not run in this release |
| Full OS sandbox for forged tools | ⚠️ **Not implemented** | Subprocess boundary only; see Known Limitations |

---

## 🌟 Core Breakthroughs

### 1. 🧠 Multi-Engine Resilient Neural Gateway
Connects **Groq** (primary high-speed inference), **Google Gemini 2.0** (deep reasoning fallback), **OpenRouter**, and **Local LLMs** (Ollama/vLLM).
* **Semantic Call Repair:** Automatically repairs and recovers malformed tool calls, Python syntax signatures (`ACTION: tool_name("arg")`), JSON blocks, and XML tags — guaranteeing arguments are never silently lost.

### 2. 👁️ Native Windows UI Automation (UIA)
Replaces fragile YOLO icon-guessing with Windows native Accessibility Tree.
* Identifies exact element names, automation IDs, and bounding boxes in milliseconds.
* Seamlessly clicks, types, and verifies visual changes with closed-loop screenshot diffing.

### 3. 🛠️ Approval-Gated Tool Forge
When faced with an impossible task, Beru proposes a new Python tool, validates it statically (AST filter + compile check), autonomously repairs syntax errors via AI up to 3 times, and — after explicit user approval — executes it in a **dedicated subprocess sandbox** (`forge_sandbox.py`).

The sandbox provides:
- **Process boundary** — forged code runs in a separate Python interpreter (`python -I`)
- **Environment isolation** — `*KEY*`, `*TOKEN*`, `*SECRET*` env vars are stripped before subprocess launch
- **Timeout enforcement** — hard 15-second cap per invocation; infinite loops are killed
- **No in-process execution** — forged code never runs in the agent's process under any code path (proposal, activation, rollback, startup, or invocation)

**Limitations of the current sandbox** (documented honestly, not overclaimed):
- Filesystem is **not** chroot'd — a forged tool can still read/write outside `workspace/` if it tries
- Network is **not** blocked at the OS level — forged tools can make outbound HTTP calls (though no API keys means no auth to services)
- Child processes spawned by a forged tool are **not** guaranteed to be terminated at timeout — only the immediate child is killed

Full OS sandboxing (seccomp / cgroups / Windows Job Objects) remains a v3.0 architectural item. The current implementation provides a **real process boundary with verified isolation** (see `test_security.py` tests) — not a full OS sandbox, and not claimed to be.

### 4. 💻 Developer Mode (Maximum Power)
* Multi-file project architect (Read, Write, Diff-patch).
* Autonomous Git interface (`status`, `diff`, `log`, `branch`, `commit`).
* Test-Driven Development (TDD) runner with automated `pytest` verification.
* One-click Windows `.exe` binary compilation via PyInstaller.

### 5. 🛡️ Tester Mode (Senior QA & Vulnerability Auditor)
* Static AST code scanner detecting OWASP Top 10 flaws, empty exception handlers, hardcoded secrets, and SQL/command injection vulnerabilities.
* Automated `pytest` suite generator for functions and classes with edge-case coverage.

### 6. 🕵️ Hacker Mode (Ethical Security & OSINT Master)
* Deep DNS enumeration (A, AAAA, MX, TXT, NS, PTR, SOA) via DoH.
* Multi-threaded port scanner with service banner grabbing.
* HTTP Security Header & Cookie Posture Auditor (CSP, HSTS, CORS, X-Frame-Options).
* SSL/TLS certificate inspector (cipher suites, expiration, SANs).

### 7. 🌐 Autonomous Web Browser Agent (Playwright)
* Dedicated worker thread architecture to prevent event loop collisions.
* Fast anti-bot resistant web search and DOM content summarizer.

### 8. 📱 Remote Control via Telegram & Proactive Daemon
* Control your PC from anywhere on your phone with `/dev`, `/hack`, `/test`, `/health`, and `/screenshot`.
* Proactive background daemon monitoring RAM/CPU spikes and dispatching native Windows toast notifications.

---

## 🏗️ Architecture

```mermaid
flowchart TD
  U[CLI / Streamlit / Telegram] --> A[Agent ReAct Loop]
  A --> I[Intent Fast Path]
  A --> B[Brain: memory, planning, verification]
  A --> G[Gateway: response cache + provider fallback]
  G --> P1[Groq] --> P2[Gemini] --> P3[OpenRouter] --> P4[Local LLM]
  A --> T[Tool Registry]
  T --> OS[Windows UI / OS tools]
  T --> WEB[Playwright Browser]
  T --> DEV[Developer / Tester / Hacker modes]
  B --> DB[(SQLite memory)]
  A --> TR[JSONL traces]
  T --> FS[Forge Sandbox: subprocess boundary]
