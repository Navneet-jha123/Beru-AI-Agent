"""
agent.py - Master Sovereign ReAct Loop for BERU AI AGENT.
Integrates:
  - Multi-tier Provider Gateway
  - Persona Enforcement (General, Developer, Tester, Hacker)
  - Cognitive Planning & Working Memory
  - Semantic Loop Guards & Call Error Recovery
  - Grounding Verification Critic
  - Full JSONL Session Tracing
"""
import inspect
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from config import TRACES_DIR
logging.basicConfig(
    filename=str(TRACES_DIR / "agent_errors.log"),
    level=logging.ERROR,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from brain import (
    WorkingMemory, plan_task, recall_lessons, verify_answer,
    record_episodic_event, get_cross_session_context,
    generate_self_reflection, save_lesson, record_tool_outcome,
)

from config import MAX_TOOL_ROUNDS, PRIMARY_MODEL, TOOL_RESULT_CAP, TRACES_DIR
from gateway import ToolCall, ask_ai
from tools_registry import get_live_schemas, get_live_tools


# --------------------------------------------------------------------------- #
# System Personas (High Limit Power)
# --------------------------------------------------------------------------- #
BASE_SYSTEM_PROMPT = """You are BERU AI AGENT — India's Most Advanced Sovereign Autonomous OS Agent.
Created and engineered by Navneet Jha.
You are Jack of All Trades and Master of All.
You do not just generate text — you take bold, precise, autonomous action.

Core Operational Directives:
1. Speak concisely, authoritatively, and with precision. Match the user's language (English, Hinglish, or Hindi).
2. Always prefer taking action with your tools rather than giving passive advice.
3. If data is retrieved by a tool, summarize it accurately in your FINAL ANSWER. Never invent facts.
4. If you lack a tool for a specific problem, call `forge_new_tool` to synthesize it, then STOP and ask the user for approval. Call `approve_tool` only after the user explicitly confirms. Never pass `confirm=True` to `forge_new_tool` without user consent.
5. Stop cleanly when the goal is achieved.
"""

PERSONA_PROMPTS = {
    "General": BASE_SYSTEM_PROMPT + """
MODE: GENERAL ASSISTANT (High Autonomy).
You manage the operating system, automate web browsing, launch apps, inspect screens with UIA, and answer complex questions.
""",

    "Developer": BASE_SYSTEM_PROMPT + """
MODE: DEVELOPER (Maximum Power Level).
You are a Staff Software Architect & Full-Stack Systems Engineer.
- You write production-grade code, read project structures, and apply clean diff-patches.
- You run tests with `run_test_suite` and shell commands with `run_dev_command`.
- You manage Git repositories (`git_action`), create branches, and write informative commit messages.
- You compile standalone binaries with `compile_to_exe`.
- NEVER leave empty placeholder functions. Complete code end-to-end.
""",

    "Tester": BASE_SYSTEM_PROMPT + """
MODE: TESTER (Senior QA & Security Auditor).
You are a Principal QA Engineer and Application Security Auditor.
- Use `audit_code_security` to scan Python codebases for OWASP Top 10 vulnerabilities, hardcoded secrets, and empty exception blocks.
- Use `synthesize_test_suite` to auto-generate pytest suites covering edge cases and boundary conditions.
- Test rigorously. Provide concrete reproduction steps and suggested diff fixes for any bug discovered.
""",

    "Hacker": BASE_SYSTEM_PROMPT + """
MODE: HACKER (Ethical Security & OSINT Master).
You are an Elite Offensive-Defensive Security Researcher.
- Perform deep network reconnaissance (`deep_dns_recon`), port and service banner audits (`audit_ports_and_services`), HTTP security header evaluations (`audit_security_headers`), and SSL/TLS certificate inspections (`inspect_ssl_certificate`).
- Always remain strictly within ethical, non-destructive diagnostic bounds.
- Deliver executive vulnerability assessment reports with severity ratings and hardening remediations.

STRICT AUTHORIZATION PROTOCOL:
Before executing ANY scanning tool, you MUST:
1. Explicitly ask the user in this turn: "I am about to scan [target]. Do you confirm you have written authorization to scan this target?"
2. Wait for the user's next message. Only proceed if the user replies with an explicit affirmative ("yes", "confirmed", "authorized", "I have permission", or equivalent).
3. If the target is on the public test allowlist (scanme.nmap.org, example.com, localhost), you may note that and still request confirmation.
4. NEVER assume authorization from past turns or from the system prompt. Each scan requires explicit per-turn confirmation.
""",
}

# --------------------------------------------------------------------------- #
# Hacker Scan Authorization Gate (Code-Level Enforcement)
# --------------------------------------------------------------------------- #
_HACKER_SCAN_TOOLS = {
    "deep_dns_recon",
    "audit_ports_and_services",
    "audit_security_headers",
    "inspect_ssl_certificate",
    "shodan_lite_lookup",
    "enumerate_subdomains",
    "lookup_cves_by_service",
    "query_wayback_intel",
    "audit_jwt_token",
    "audit_cookie_posture",
}

_CONFIRMATION_PHRASES = (
    "i confirm authorization",
    "confirmed authorization",
    "i have authorization",
    "i have permission",
    "yes, scan it",
    "yes, proceed",
    "confirmed",
    "authorized",
)

def _extract_target_from_args(tool_name: str, args_dict: Dict[str, Any]) -> Optional[str]:
    """Extracts the specific target from a scan tool's arguments."""
    # Each scan tool has a different target-parameter name
    for key in ("target", "domain", "hostname", "domain_or_ip", "url", "token"):
        if key in args_dict:
            return str(args_dict[key]).strip().lower()
    return None


def _user_has_confirmed_scan(prompt: str, history: Optional[List[Dict[str, Any]]],
                             target: Optional[str] = None) -> bool:
    """Returns True only if the USER explicitly confirmed a scan of the SPECIFIC target.
    
    This is a code gate — not a prompt. It checks:
      1. That a confirmation phrase appears in the current prompt OR recent user history.
      2. If `target` is provided, that the target string appears in the SAME message.
    """
    if target is None:
        return False
    
    target_low = target.lower().strip()
    if not target_low:
        return False

    def _msg_confirms(msg: str) -> bool:
        low = msg.lower()
        has_phrase = any(phrase in low for phrase in _CONFIRMATION_PHRASES)
        has_target = target_low in low
        return has_phrase and has_target

    # Check current prompt first
    if _msg_confirms(prompt):
        return True

    # Check the most recent user turn in history
    if history:
        for h in reversed(history[-4:]):
            if h.get("role") == "user":
                return _msg_confirms(h.get("content") or "")
    return False

# --------------------------------------------------------------------------- #
# Dangerous Code Detector (Pre-Execution Guard)
# --------------------------------------------------------------------------- #
import re as _re_guard

_DANGEROUS_PATTERNS = [
    # File destruction
    r"os\.remove\s*\(",
    r"os\.unlink\s*\(",
    r"os\.rmdir\s*\(",
    r"shutil\.rmtree\s*\(",
    r"Path\([^)]+\)\.unlink\s*\(",
    # Shell injection
    r"subprocess\.(run|call|Popen)\s*\([^)]*shell\s*=\s*True",
    r"os\.system\s*\(",
    r"os\.popen\s*\(",
    # Code injection
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__\s*\(",
    # Mass deletion patterns
    r"os\.walk\s*\(\s*['\"][A-Z]:",
    r"glob\.glob\s*\(\s*['\"][A-Z]:",
    # Network exfiltration
    r"requests\.(post|put)\s*\(",
    r"urllib\.request\.urlopen\s*\(",
    # Credential theft
    r"open\s*\(\s*['\"][^'\"]*\.env",
    r"open\s*\(\s*['\"][^'\"]*id_rsa",
]

def _scan_for_malicious_code(text: str) -> list:
    """Scans text for dangerous code patterns. Returns list of found issues."""
    if not text:
        return []
    issues = []
    for pattern in _DANGEROUS_PATTERNS:
        if _re_guard.search(pattern, text):
            clean_pattern = pattern.replace("\\", "").replace("(", "").replace(")", "").replace("\\s*", " ")
            issues.append(clean_pattern)
    return list(set(issues))


# --------------------------------------------------------------------------- #
# Execution Tracer
# --------------------------------------------------------------------------- #
class SessionTracer:
    def __init__(self, trace_id: str, prompt: str, mode: str):
        self.trace_id = trace_id
        self.file_path = TRACES_DIR / f"{trace_id}.jsonl"
        self._log("session_start", {"prompt": prompt, "mode": mode, "time": time.strftime("%Y-%m-%dT%H:%M:%S")})

    def _log(self, event_type: str, data: Dict[str, Any]):
        entry = {"time": time.strftime("%H:%M:%S"), "type": event_type, "data": data}
        with open(self.file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def log_llm_reply(self, provider: str, content: str, tool_calls: List[str]):
        self._log("llm_reply", {"provider": provider, "content": content, "tool_calls": tool_calls})

    def log_tool_result(self, tool_name: str, args: Dict[str, Any], result: str, duration: float):
        self._log("tool_result", {"tool": tool_name, "args": args, "result": result[:1000], "duration_sec": round(duration, 3)})

    def log_finish(self, final_answer: str):
        self._log("session_finish", {"final_answer": final_answer[:2000], "time": time.strftime("%Y-%m-%dT%H:%M:%S")})


# --------------------------------------------------------------------------- #
# Tool Dispatcher
# --------------------------------------------------------------------------- #
def _invoke_tool(tool_name: str, raw_args: Any, tools_dict: Dict[str, Callable]) -> str:
    fn = tools_dict.get(tool_name)
    if fn is None:
        return f"Unknown tool: '{tool_name}'."

    # Parse args
    if isinstance(raw_args, str):
        try:
            kwargs = json.loads(raw_args) if raw_args.strip() else {}
        except Exception:
            kwargs = {}
    elif isinstance(raw_args, dict):
        kwargs = raw_args
    else:
        kwargs = {}

    # 🛡️ SANDBOX: Forged tools are stored as Path markers, not callables.
    # Route every forged invocation through the subprocess boundary.
    try:
        from forge import ACTIVE_FORGED_TOOLS
    except Exception:
        ACTIVE_FORGED_TOOLS = {}

    if tool_name in ACTIVE_FORGED_TOOLS:
        from forge_sandbox import run_forged_tool_in_subprocess
        from config import FORGE_DIR
        tool_file = FORGE_DIR / f"{tool_name}.py"
        return run_forged_tool_in_subprocess(
            tool_file=tool_file,
            func_name=tool_name,
            kwargs=kwargs,
            timeout=15,
        )

    # Native tool — safe to introspect and call in-process.
    sig = None
    try:
        sig = inspect.signature(fn)
        # Drop unrecognized args if function doesn't accept **kwargs
        if not any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            kwargs = {k: v for k, v in kwargs.items() if k in sig.parameters}

        # Native tool — safe to run in-process.
        res = fn(**kwargs)
        return str(res) if res is not None else "Done (no output)."
    except TypeError as te:
        expected = list(sig.parameters.keys()) if sig else "unknown (signature not inspectable)"
        return f"Tool TypeError: {te}. Expected parameters: {expected}"
    except Exception as e:
        return f"Tool Execution Error: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# Master Agent Run Loop
# --------------------------------------------------------------------------- #
def run_agent(
    prompt: str,
    mode: str = "General",
    history: Optional[List[Dict[str, Any]]] = None,
    on_thought: Optional[Callable[[str], None]] = None,
    on_tool_call: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    on_tool_result: Optional[Callable[[str, str], None]] = None,
) -> str:
    """
    Executes a complete sovereign ReAct session.
    """
    trace_id = uuid.uuid4().hex[:8]
    tracer = SessionTracer(trace_id, prompt, mode)

    # 1. Setup Tools & Schemas
    tools_dict = get_live_tools()
    schemas = get_live_schemas()

    # --- Deterministic fast paths (no LLM round-trip) ---
    simple = prompt.strip()

    def _fast_dispatch(tool_name: str, parsed_args: Dict[str, Any]) -> str:
        """
        Shared instrumentation wrapper for fast-path tool execution.
        Fires on_tool_call/on_tool_result/record_tool_outcome so the benchmark
        and UI see the same telemetry as the LLM path.
        """
        if on_tool_call:
            try:
                on_tool_call(tool_name, parsed_args)
            except Exception:
                pass

        t0 = time.time()
        result = _invoke_tool(tool_name, json.dumps(parsed_args), tools_dict)
        duration = time.time() - t0

        success = not result.startswith(
            ("Failed", "Tool ", "Unknown", "Tool Execution Error", "Tool TypeError")
        )
        try:
            record_tool_outcome(tool_name, success)
        except Exception:
            pass

        tracer.log_tool_result(tool_name, parsed_args, result, duration)

        if on_tool_result:
            try:
                on_tool_result(tool_name, result)
            except Exception:
                pass

        return result

    m = re.fullmatch(
        r"(?i)(?:open|launch|start)\s+(?:the\s+)?(calc|calculator|notepad|paint|chrome|edge|vscode|explorer|cmd|terminal)",
        simple,
    )
    if m and "open_application" in tools_dict:
        result = _fast_dispatch("open_application", {"app_name": m.group(1)})
        tracer.log_finish(result)
        return result

    if re.fullmatch(r"(?i)(health|system health|health status|/health)", simple) and "get_system_health" in tools_dict:
        result = _fast_dispatch("get_system_health", {})
        tracer.log_finish(result)
        return result

    m2 = re.fullmatch(r"(?i)(?:search\s+google|google|search)\s+(.+)", simple)
    if m2 and "browser_search" in tools_dict:
        result = _fast_dispatch("browser_search", {"query": m2.group(1)})
        tracer.log_finish(result)
        return result

    # 2. Setup Persona & Working Memory
    system_text = PERSONA_PROMPTS.get(mode, PERSONA_PROMPTS["General"])
    continuity = get_cross_session_context()          # ← ADD
    if continuity:                                     # ← ADD
        system_text += "\n\nRECENT SESSION CONTEXT:\n" + continuity[:2500]
    # Ingest lessons
    lessons = recall_lessons(prompt)
    if lessons:
        system_text += "\n\nRECALLED HISTORICAL LESSONS:\n" + "\n".join(f"- {l}" for l in lessons)

    working_memory = WorkingMemory()
    # Autonomous plan
    plan_steps = plan_task(prompt, mode, list(tools_dict.keys()))
    if plan_steps:
        working_memory.set_todos(plan_steps)
        if on_thought:
            on_thought(f"📋 Formulated Plan:\n" + "\n".join(f"- {s}" for s in plan_steps))

    # 3. Initialize Messages
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_text}]
    if history:
        for h in history[-8:]:  # Keep recent context
            messages.append(h)
    messages.append({"role": "user", "content": prompt})

    # Call Tracking for Loop Guard
    executed_calls_history: List[str] = []

    # Track whether the todo checklist has already been injected into the
    # current user turn, so the corrective-round loop cannot stack it.
    todo_injected = False

    for round_num in range(1, MAX_TOOL_ROUNDS + 1):
        # Inject current working memory checklist if present (once per user turn)
        todo_text = working_memory.format_todo_pad()
        if (
            todo_text
            and not todo_injected
            and messages[-1]["role"] == "user"
        ):
            messages[-1]["content"] += f"\n\n{todo_text}"
            todo_injected = True

        try:
            ai_msg = ask_ai(messages, tools=schemas, available_tools_dict=tools_dict, temperature=0.2)
        except Exception as e:
            err = f"AI Generation Failed: {e}"
            tracer.log_finish(err)
            return err

        tool_names = [tc.function.name for tc in ai_msg.tool_calls]
        tracer.log_llm_reply(ai_msg.provider, ai_msg.content, tool_names)

        # 🛑 SECURITY GUARD: Scan tool-call arguments for malicious code.
        # Only scans tool_calls (not plain text replies) to avoid false positives
        # when the user asks legitimate questions like "what does os.remove do?"
        if ai_msg.tool_calls:
            warnings = []
            for tc in ai_msg.tool_calls:
                # Only scan arguments for tools that write or execute code
                if tc.function.name in ("write_project_file", "apply_code_patch",
                                        "run_dev_command", "compile_to_exe",
                                        "forge_new_tool", "run_fuzz_testing",
                                        "run_mutation_testing"):
                    warnings.extend(_scan_for_malicious_code(str(tc.function.arguments)))

            if warnings:
                block_msg = (
                    "🛑 **SECURITY BLOCK**\n\n"
                    "The AI attempted to write or execute code containing dangerous patterns:\n"
                    + "\n".join(f"- `{w}`" for w in warnings)
                    + "\n\n**I cannot write or run this code.** "
                    "If you are intentionally testing a security vulnerability, please use a disposable sandbox, "
                    "not your main OS."
                )
                tracer.log_finish(block_msg)
                return block_msg

        # Emit thought if model produced textual reasoning before tool call
        if ai_msg.content and on_thought:
            on_thought(ai_msg.content)

        # If no tool calls, this is the final answer!
        if not ai_msg.tool_calls:
            final_answer = ai_msg.content.strip()

            # Verification Critic
            ok, critic_note = verify_answer(
                final_answer,
                working_memory.tool_evidence,
                prompt_len=len(prompt),
            )

            # If the critic rejected the answer AND we still have rounds left,
            # inject the corrective feedback and try again. If we've run out of
            # rounds, fall through and return whatever we have instead of
            # discarding a perfectly good answer.
            if not ok and round_num < MAX_TOOL_ROUNDS:
                messages.append({"role": "assistant", "content": final_answer})
                messages.append({"role": "user", "content": f"[Verification Guard]: {critic_note}"})
                todo_injected = False  # allow checklist refresh on the corrective turn
                continue

            # Final safety net: never return an empty string.
            if not final_answer:
                final_answer = "Unable to produce a verified answer within the allowed rounds."

            tracer.log_finish(final_answer)
            try:
                record_episodic_event(trace_id, prompt, final_answer, mode)
                if len(prompt) > 100:
                    # Pass the *actual* verification outcome instead of hardcoded True
                    reflection = generate_self_reflection(prompt, final_answer, ok)
                    if reflection:
                        save_lesson(mode.lower(), reflection, prompt[:500])
            except Exception as e:
                logging.error(f"memory write failed: {e}")
                tracer._log("memory_warning", {"error": str(e)[:300]})
            return final_answer

        # Process Tool Calls
        # Convert assistant message with tool calls into history
        assistant_turn = {
            "role": "assistant",
            "content": ai_msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in ai_msg.tool_calls
            ],
        }
        messages.append(assistant_turn)

        for tc in ai_msg.tool_calls:
            t_name = tc.function.name
            t_args_str = tc.function.arguments
            call_sig = f"{t_name}:{t_args_str.strip()}"

            # Loop Guard: Prevent repeating identical failing call 3 times
            if executed_calls_history.count(call_sig) >= 2:
                guard_msg = f"Loop Guard: Tool '{t_name}' with these exact arguments already failed twice. Change your approach or explain the obstacle."
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": t_name, "content": guard_msg})
                continue

            executed_calls_history.append(call_sig)

            # 🔒 HACKER AUTHORIZATION GATE — code-level, target-bound
            if mode == "Hacker" and t_name in _HACKER_SCAN_TOOLS:
                # Extract the target from tool args to bind confirmation to it
                try:
                    _gate_args = json.loads(t_args_str) if isinstance(t_args_str, str) else t_args_str
                except Exception:
                    _gate_args = {}
                _gate_target = _extract_target_from_args(t_name, _gate_args)
                
                if not _user_has_confirmed_scan(prompt, history, target=_gate_target):
                    block_msg = (
                        f"🛑 AUTHORIZATION REQUIRED for target '{_gate_target}': "
                        f"Before running '{t_name}', you must ask the user in a separate turn: "
                        f"'I am about to scan {_gate_target}. Do you confirm you have authorization?' "
                        f"Then wait for the user to reply with BOTH a confirmation AND the target name. "
                        f"Generic confirmations without the target will not authorize the scan."
                    )
                    messages.append({"role": "tool", "tool_call_id": tc.id, "name": t_name, "content": block_msg})
                    continue

            # Parse args for callback
            try:
                parsed_args = json.loads(t_args_str) if isinstance(t_args_str, str) else t_args_str
            except Exception:
                parsed_args = {}

            if on_tool_call:
                on_tool_call(t_name, parsed_args)

            # Execute tool
            t0 = time.time()
            result = _invoke_tool(t_name, t_args_str, tools_dict)
            duration = time.time() - t0
            success = not result.startswith(("Failed", "Tool ", "Unknown", "Tool Execution Error", "Tool TypeError"))
            try:
                record_tool_outcome(t_name, success)
            except Exception as _e:
                logging.error(f"record_tool_outcome failed for {t_name}: {_e}")

            # Record in working memory and tracer
            working_memory.record_tool_result(t_name, parsed_args, result)
            tracer.log_tool_result(t_name, parsed_args, result, duration)

            if on_tool_result:
                on_tool_result(t_name, result)

            # Update checklist if task completed
            if t_name in ("write_project_file", "compile_to_exe", "audit_code_security", "deep_dns_recon"):
                working_memory.mark_done(t_name)

            # Cap tool result to avoid token overload
            capped_result = result[:TOOL_RESULT_CAP]
            if len(result) > TOOL_RESULT_CAP:
                capped_result += f"\n... [Truncated: {len(result) - TOOL_RESULT_CAP} additional characters]"

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": t_name,
                "content": capped_result,
            })

    final_fallback = "Reached maximum tool execution rounds without a terminal answer."
    tracer.log_finish(final_fallback)
    return final_fallback
