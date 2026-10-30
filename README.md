# BERU local privacy and analysis patch

This folder contains only the files to add or replace in `C:\course Projects\AI Agent`. The source project was not overwritten.

## Apply manually

1. Back up the current project folder.
2. Copy only the files listed below into the project root, keeping the `modes/` subfolder structure. Replace matching files when Windows asks. Do not copy the validation/cache folders.
3. Keep your existing `.env` file; this patch does not include or replace credentials.
4. From the project folder, run `python -m pip install -r requirements.txt` and restart BERU.
5. Select **Medical** or **Reverse Engineering** in the left “Help me with” menu.

Files included:

- New: `privacy_gateway.py`, `modes/medical.py`, `modes/reverse_engineering.py`
- Replace: `agent.py`, `gateway.py`, `tools_registry.py`, `modes/tools_bundles.py`, `app.py`, `requirements.txt`

The registry, app, and dependency list also need edits; the original plan omitted those files even though its functions are defined or selected there.

## What it does

- PII redaction masks common email addresses, IPv4 addresses, and local file paths in model messages and tool arguments. Returned text and tool arguments are rehydrated for the local app. Response caching is disabled for gateway calls so placeholder mappings cannot be confused between requests. Image/audio/file attachments are omitted by the filter because regex cannot inspect their contents.
- Medical and Reverse Engineering run through a request-scoped local-only context. Only their corresponding local tools are offered; web, forged, write, and unrelated tools are not available in those modes. Local-only mode rejects a model URL that is not localhost or a loopback IP and does not fall back to a cloud model. Sensitive prompts are not added to persistent lessons or cross-session context.
- The medical PDF tool reads up to 40 pages / 20 MB of selectable PDF text locally. It extracts a small list of common values and compares only against a reference interval detected on the same line. It does not OCR, diagnose, or give treatment advice. The symptom function is a limited phrase matcher and cannot rule out emergencies.
- Reverse engineering reads at most 64 MB per file and returns bounded output. PE parsing, string extraction, and disassembly are static; analyzed samples are not executed or uploaded by these tools.
- The `sports` bundle is an empty reserved bundle. This project has no sports data tools/provider, so it does not return schedules or scores.

## Limits and existing audit findings

No code can honestly be guaranteed “100% secure” or “zero bugs.” Regex redaction is best effort and cannot identify every PII type. It covers calls routed through `gateway.ask_ai` and `gateway.ask_ai_from_provider`; it does not stop unrelated network-enabled tools in other modes from sending their own inputs to external services. Local-only here means the configured model endpoint is loopback on the same machine. A remote Mac/Ollama endpoint will be blocked.

The existing project security scanner reported 80 `Silent Exception` findings across 24 Python files in the staged project. That scanner treats every one-line `except: pass/continue` as HIGH and is heuristic; each finding needs review rather than being treated as a confirmed vulnerability. Unrelated existing files were not changed in this patch.

## Verification performed

- Python syntax compilation passed for the patch files.
- Tool registry parity passed: 134 tools and 134 schemas.
- Existing `test_security.py`: 27 passed in a staged copy of the project.
- Targeted checks passed for redaction/rehydration, attachment omission, local-only cloud blocking, reference-interval parsing, BMI input bounds, and emergency-phrase handling.
- `capstone` and `pdfplumber` were not installed in the validation environment. The tools return a clear dependency message if either is missing; installation is handled by the updated requirements file.

This is a reviewed implementation, not a professional medical device, malware verdict, or independent security certification.
# Local data, API, monitoring, and screen analysis upgrades

Install the added data/YAML dependencies with `pip install -r requirements.txt`.
Data Analyst mode uses the configured localhost model and exposes read-only
CSV/SQLite/Excel tools. Data paths must resolve inside this project or its
workspace; CSV/SQLite results are capped at 1,000 rows.

API mode also requires the local model. Review a spec before ingesting it. Add
exact DNS names to `BERU_API_ALLOWED_HOSTS`; remote spec URLs and API servers
must use those hosts. HTTPS and GET-only calls are the defaults. Enable HTTP or
mutating calls only when required and after reviewing the specific target.
Credentials belong in environment variables and may be referenced as
`${ENV:NAME}` in supported auth headers. Specs are retained in process memory;
restart the app to clear them.

Watchdog resource rules emit a high-resource event only after a 90% CPU/RAM or
95% disk threshold persists for five minutes. `run_agent` actions are
read-only-intended background diagnostics with a ten-minute per-rule cooldown.
Windows service restart is disabled until exact names are listed in
`BERU_RESTARTABLE_SERVICES`.

Screen UI Automation remains available. Optional YOLO detection needs an
operator-provided, locally reviewed `.pt` file configured with
`BERU_YOLO_MODEL`; BERU does not download or train a model automatically.
Button/input/checkbox detection training requires a labeled local dataset and
locally stored YOLO weights. `python train_ui_detector.py --dataset
workspace/ui_data.yaml --weights workspace/yolov8n.pt` prompts for an explicit
confirmation, then writes output under `workspace/beru_yolo_runs/`. Install
Ultralytics separately only after reviewing its dependencies.
