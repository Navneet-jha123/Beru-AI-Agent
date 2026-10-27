# ⚡ BERU AI AGENT
### *India's Sovereign Autonomous OS Agent | Jack of All Trades, Master of All*

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
| 110 tools registered (99 original + 4 stock + 7 malware) | ✅ Verified | `python -c "from tools_registry import get_live_tools; print(len(get_live_tools()))"` |
| 110 schemas registered (99 original + 4 stock + 7 malware) | ✅ Verified | `python -c "from tools_registry import get_live_schemas; print(len(get_live_schemas()))"` |
| Tool/schema parity | ✅ Verified | `python -c "from tools_registry import validate_registry_parity; print(validate_registry_parity())"` |
| Security tests pass | ✅ Verified | `python -m pytest test_security.py -v` (27/27 passing) |
| Malware scanner operational | ✅ Verified | Manually tested against a dummy malware file; successfully quarantined and deleted. |
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

### 9. 🧪 Malware Scanner & Quarantine (NEW — Feature 51)
* Hash-reputation lookup (SHA-256 vs. VirusTotal community detections, optional free API key) and offline static heuristics (disguised double extensions, process-injection API strings, obfuscated PowerShell/VBS launchers, Office macro auto-run triggers, PE-header sanity checks) — each finding returned with a 0–100 risk score and a plain-language explanation.
* **Quarantine, never delete:** flagged files are moved to `workspace/quarantine/`, set read-only and non-executable, and logged with their original path, reason, and SHA-256. Fully reversible via `restore_from_quarantine`.
* Permanent deletion (`delete_quarantined_file`) requires an explicit, separate `confirm=True` — a scan result alone can never trigger it.
* `sweep_directory_for_threats` scans an entire folder (e.g. Downloads) in one call and auto-quarantines anything above a configurable risk threshold.
* **By design, does not attempt in-place virus disinfection** — stripping a payload from an infected file while preserving the rest requires virus-family-specific signatures that only maintained AV engines carry. Quarantine is the safe, honest substitute; see CHANGELOG for the full rationale.

---

### 10. Feature 52: Multi-Timeframe Stock Synthesis (`market_analyst.py`) — NEW
Advanced quantitative intraday engine that merges 5-minute, 30-minute, and Daily technical data into a single "Executive Verdict."
- **`analyze_30m_swing_momentum`** — Filters out 5-minute noise by analyzing 30-minute candles, SMA5, and 30m RSI to detect medium-term intraday swings.
- **`synthesize_market_verdict`** — A decision matrix that cross-references all three timeframes. It detects edge cases like "Healthy Pullbacks" (Daily Bullish + Intraday Bearish) or "Bull Traps" (Daily Bearish + Intraday Bullish).
- **⚠️ Preliminary Backtest:** An earlier informal test across 10 large-cap equities indicated ~83% directional alignment on selected setups. This is **not** a validated, out-of-sample backtest. It lacks a stated data period, benchmark, slippage/fee modeling, and confidence intervals. Treat as unverified and do not rely on it for trading decisions.

---

### 11. Multi-Timeframe Synthesis & 30-Minute Swing Engine
In addition to daily candles, BERU features a high-probability intraday engine that merges 5-minute momentum, 30-minute swing trends, and Daily macro data. The `synthesize_market_verdict` tool acts as an AI decision matrix. For example, if the Daily is Bullish (+2) but the 5m/30m are Bearish (-1, -2), it correctly identifies a **"Healthy Pullback"** and advises against buying calls until the short-term trend aligns. An earlier informal test across 10 large-cap Indian equities indicated ~83% directional alignment, but this was not a reproducible out-of-sample study. Treat as unverified and do not rely on it for trading decisions.

---

### 13. 📈 Read-only Stock Data Analysis (India + US)

BERU analyzes OHLCV candles for India and US listings using local CSV files, native Alpha Vantage and Twelve Data adapters, or a provider-neutral HTTPS endpoint. Add your Alpha Vantage key as ALPHA_VANTAGE_API_KEY=your_key in the ignored .env file and restart BERU. The adapter resolves company names and fetches daily/weekly candles automatically; the free key currently allows 25 API requests per day, and this adapter does not enable Alpha Vantage intraday data. The daily compact response provides up to 100 recent records, enough for swing history but not always BERU's 200-bar long-term minimum. India symbols use the exchange suffix returned by provider search; US venue is reported exchange-neutral because the search result does not supply a venue. BERU coordinates specialist evidence agents and reports historical analog scenarios. The Plotly-based Market Lab tab renders interactive candles. The screen_stock_watchlist tool compares up to 20 symbols using change, SMA 20/50/200, RSI, relative volume, ATR, and candle time; rows are ordered by the difference between positive and negative evidence counts, which is not a buy/sell signal. BERU does not issue personalized trade recommendations or place orders.

### 14. 🏗️ Universal Engineering Lab (NEW — Feature 53)
*   **Visual AR Mode:** Uses OpenCV + MediaPipe to build 2D structures in the air using pinch gestures. Real-time Finite Element Analysis (FEA) computes tension yield and Euler buckling.
*   **Universal Physics Router:** Simulates structural (bridges, car chassis), electrical (transformers, diodes, LEDs), thermal (CPUs, GPUs, laptops), and logic (ALUs, adders, gates) models.
*   **Mathematically Verified:** A 42-test mathematical verification suite (`python modes/universal_lab.py selftest`) proves that all physics calculations (Euler buckling, Faraday's law, thermal resistance, logic truth tables) are accurate. 


### Optional: Twelve Data

Set `TWELVE_DATA_API_KEY` in the ignored `.env` file. Set `BERU_MARKET_PROVIDER=twelve_data` to select it explicitly; `auto` prefers Twelve Data when its key is present, otherwise Alpha Vantage. Restart BERU, then check `market_data_status`. The adapter supports normalized daily and intraday intervals only where your Twelve Data plan grants access. Free-tier quotas, country/exchange coverage, options/futures coverage, and real-time entitlements differ; verify TCS/WIPRO and the desired contract in your account before relying on it. BERU's Twelve Data adapter is for OHLCV stock candles and does not claim to provide futures/options chains.

### Connect your Alpha Vantage key

1. Copy the key from your Alpha Vantage account.
2. Open the project’s existing .env file and set ALPHA_VANTAGE_API_KEY=your_key (replace your_key with your key; do not include quotes). Do not put the key in .env.example, source code, or a message.
3. Restart BERU, then ask it to analyze a company name such as TCS. It uses Alpha Vantage symbol search and requests that listing’s daily candles. For the chart, use the Market Lab tab and enter a ticker; the India exchange selection is appended when needed.
4. Call market_data_status if BERU still reports CSV mode. It does not reveal the key.

This adapter uses Alpha Vantage’s free daily/weekly history and symbol-search endpoints. The daily endpoint’s free compact response contains the latest 100 data points. Intraday requests are not supported by this adapter; Alpha Vantage marks its intraday endpoint as premium. Provider quotas and exchange coverage can change, so check the provider account and its current documentation.
### Compare a watchlist

Ask BERU to screen a list of up to 20 India or US tickers (for example, “compare RELIANCE, TCS, INFY”). The tool fetches daily candles through the configured provider or reads the matching CSV files, rejects stale/short data per symbol, and reports auditable indicator columns with individual data errors. It orders rows by the difference between simple positive and negative evidence counts; these counts are descriptive only, not a forecast or recommendation. This takes the screener comparison idea while keeping BERU's source, timestamp, and limitations visible.

### Configure automatic fetching

In `.env`, set `BERU_MARKET_DATA_URL` to an HTTPS candle endpoint. It accepts `market`, `exchange`, `symbol`, `interval`, and `limit`, and returns JSON in this normalized shape (timestamps must include a UTC offset):

```json
{"source":"Your provider","candles":[{"timestamp":"2026-10-23T09:15:00+05:30","open":100,"high":101,"low":99.5,"close":100.5,"volume":12000}]}
```

Set `BERU_MARKET_SEARCH_URL` to an HTTPS search endpoint. It must accept `query`, `market`, `limit` and return `{results:[{name,symbol,market,exchange,primary}]}`. This lets a user enter just a company name; BERU selects a unique/primary listing or asks the user to resolve ambiguity. On a match it fetches daily candles automatically; intraday candles are fetched only when the active provider supports them. Optionally set `BERU_MARKET_DATA_TOKEN` for a bearer token and `BERU_MARKET_DATA_NAME` for the source label, then restart BERU. The endpoint must handle provider-specific symbol mapping, licensing, and exchange delays; BERU validates responses and never sends orders. The endpoint contract is provider-neutral, but most vendor APIs need a small adapter service because their request and response formats differ. Configure a licensed provider with current data for intraday use. When neither an Alpha Vantage key nor provider-neutral URLs are configured, automatic company-name lookup is inactive and BERU uses local CSV files or ticker-based analysis.

### Add a CSV dataset

Place a UTF-8 CSV in `workspace/market_data/`, named `market_exchange_symbol_interval.csv` (market is lowercase), for example `india_nse_reliance_5m.csv` or `us_nasdaq_msft_1d.csv`. Include these columns:

```csv
timestamp,open,high,low,close,volume
2026-10-23T09:15:00+05:30,100.0,101.0,99.5,100.5,12000
```

Timestamps must include a UTC offset. Supported horizons: intraday (1m, 5m, 15m, 30m, 1h), swing/regular (1d), and long_term (1d or 1wk). The analyzer validates the CSV, rejects malformed OHLCV data, caps files at 20 MB/10,000 bars, and requires 30, 60, or 200 bars respectively. Intraday scenarios examine about the next 60 minutes (interval adjusted); swing scenarios examine the next candle; long-term scenarios examine the next five daily bars (or next weekly candle for weekly inputs). Indicators include SMA, RSI, MACD, ATR, relative volume for non-intraday data, session VWAP intraday, recent range, and bar-to-bar change.

The analyst panel has separate trend, momentum, volume/participation, volatility/risk, historical-scenario, and skeptic/data-check agents. When enough history exists, the scenario agent finds similar past indicator states and reports next-candle/session outcomes; for daily data it also summarizes historical opening gaps. These percentages are uncalibrated frequencies from a small selected analog set, not tested forecast probabilities. Next-session open gaps cannot be reliably predicted from OHLCV candles alone.

Candles report traded volume; they do not identify distinct people buying/selling or verified buyer/seller order flow. The report shows the latest candle timestamp and rejects data older than seven days (intraday) or fourteen days (daily/weekly), allowing recent last-session data over weekends and holidays. CSV authenticity is not verified, and long-term fundamental valuation is not included. BERU gives a constructive/mixed/weak technical setup summary, not a personalized "should I buy?" decision. Investment suitability depends on personal circumstances; in India, personalized investment advice is governed by SEBI's [Investment Advisers Regulations](https://www.sebi.gov.in/legal/regulations/feb-2025/securities-and-exchange-board-of-india-investment-advisers-regulations-2013-last-amended-on-february-10-2025-_92319.html), so a production advisory service should obtain qualified compliance review. Treat outputs as educational evidence, not a guaranteed prediction.

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
