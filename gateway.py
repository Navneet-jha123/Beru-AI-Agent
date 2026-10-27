"""
gateway.py - Universal Multi-Engine Neural Gateway for BERU AI AGENT.
Connects Groq, Google Gemini (via google-genai), OpenRouter, and Local LLMs.
Features:
  - 60-Second TTL in-memory LRU Response Cache
  - Token Streaming Support
  - max_retries=0 for instantaneous failover
  - Graceful UnifiedMessage on total provider failure (never crashes caller)
  - Intelligent Tool-Call & Python-Signature Repair
"""
import ast
import asyncio
import hashlib
import json
import os
import re
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import (
    CACHE_TTL_SECONDS,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    LOCAL_LLM_MODEL,
    LOCAL_LLM_URL,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    PRIMARY_MODEL,
    GROQ_BACKUP_MODEL,
)

TIMEOUT = 35

# In-Memory 60-second TTL Cache
_CACHE_LOCK = threading.Lock()
_RESPONSE_CACHE: Dict[str, Tuple[float, Any]] = {}

# --------------------------------------------------------------------------- #
# Message-history sanitizer (keeps strict providers like OpenAI/OpenRouter happy)
# --------------------------------------------------------------------------- #
def _sanitize_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Guarantees the tool-calling protocol is valid before ANY provider call:
      - every assistant `tool_calls` entry is answered by a `tool` message,
        placed immediately after it (missing answers get a placeholder);
      - orphan `tool` messages are dropped;
      - `system` messages that landed inside a tool block are moved after it.
    The input list is never mutated.
    """
    cleaned: List[Dict[str, Any]] = []
    n = len(messages)
    i = 0
    while i < n:
        m = messages[i]
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            j = i + 1
            responses: Dict[str, Dict[str, Any]] = {}
            deferred: List[Dict[str, Any]] = []
            wanted = {tc.get("id") for tc in m["tool_calls"]}
            while j < n and messages[j].get("role") in ("tool", "system"):
                mj = messages[j]
                if mj.get("role") == "tool":
                    tid = mj.get("tool_call_id")
                    if tid in wanted and tid not in responses:
                        responses[tid] = mj
                else:
                    deferred.append(mj)
                j += 1
            cleaned.append(m)
            for tc in m["tool_calls"]:
                tid = tc.get("id")
                if tid in responses:
                    cleaned.append(responses[tid])
                else:
                    cleaned.append({
                        "role": "tool",
                        "tool_call_id": tid,
                        "name": (tc.get("function") or {}).get("name", "tool"),
                        "content": "(no result recorded)",
                    })
            cleaned.extend(deferred)
            i = j
        elif role == "tool":
            i += 1  # orphan tool message — drop
        else:
            cleaned.append(m)
            i += 1
    return cleaned


def _is_model_missing_error(err: str) -> bool:
    low = err.lower()
    return (
        "model_not_found" in low
        or "does not exist" in low
        or "no longer available" in low
        or "decommissioned" in low
        or ("404" in low and "model" in low)
    )


# Models that returned "not found" this session — skipped on later calls (saves a failed round-trip each time).
_DEAD_GROQ_MODELS: set = set()
_GEMINI_MODEL_OVERRIDE: Optional[str] = None


def _compute_cache_key(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]], temperature: float) -> str:
    serialized = json.dumps({"m": messages, "t": tools or [], "temp": temperature}, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _get_cached_response(key: str) -> Optional["UnifiedMessage"]:
    with _CACHE_LOCK:
        if key in _RESPONSE_CACHE:
            timestamp, msg = _RESPONSE_CACHE[key]
            if time.time() - timestamp < CACHE_TTL_SECONDS:
                # Return a shallow copy so callers can't mutate the cached object
                # (ask_ai's Gemini/OpenRouter recovery path rebinds msg.tool_calls).
                return UnifiedMessage(
                    content=msg.content,
                    tool_calls=list(msg.tool_calls),
                    provider=msg.provider,
                )
            del _RESPONSE_CACHE[key]
    return None


def _set_cached_response(key: str, msg: "UnifiedMessage") -> None:
    with _CACHE_LOCK:
        if len(_RESPONSE_CACHE) >= 200:
            # FIFO eviction — drop the 50 oldest entries instead of wiping the cache.
            for old_key, _ in sorted(_RESPONSE_CACHE.items(), key=lambda kv: kv[1][0])[:50]:
                _RESPONSE_CACHE.pop(old_key, None)
        _RESPONSE_CACHE[key] = (time.time(), msg)


class ToolFunction:
    def __init__(self, name: str, arguments: str):
        self.name: str = name
        self.arguments: str = arguments  # Valid JSON string or stringified parameters


class ToolCall:
    def __init__(self, name: str, arguments: Any):
        self.id: str = f"call_{uuid.uuid4().hex[:10]}"
        self.type: str = "function"
        if isinstance(arguments, dict):
            args_str = json.dumps(arguments)
        elif isinstance(arguments, str):
            args_str = arguments
        else:
            args_str = "{}"
        self.function = ToolFunction(name, args_str)


class UnifiedMessage:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[ToolCall]] = None, provider: str = "unknown"):
        self.content: str = content or ""
        self.tool_calls: List[ToolCall] = tool_calls or []
        self.provider: str = provider


# --------------------------------------------------------------------------- #
# Call Extraction & Semantic Repair
# --------------------------------------------------------------------------- #
def parse_python_call_args(args_str: str) -> Dict[str, Any]:
    """Parse Python-style call arguments like `('Paint')` or `(app_name="Paint", force=True)`."""
    args_str = args_str.strip()
    if not args_str:
        return {}
    if not (args_str.startswith("(") and args_str.endswith(")")):
        args_str = f"({args_str})"

    dummy_call = f"dummy{args_str}"
    try:
        tree = ast.parse(dummy_call, mode="eval")
        call_node = tree.body
        if not isinstance(call_node, ast.Call):
            return {}

        result: Dict[str, Any] = {}
        # Keyword arguments: foo="bar"
        for kw in call_node.keywords:
            try:
                result[kw.arg] = ast.literal_eval(kw.value)
            except Exception:
                result[kw.arg] = getattr(kw.value, "id", None) or getattr(kw.value, "s", str(kw.value))

        # Positional arguments: "Paint" -> default to common first parameters
        if call_node.args:
            pos_vals = []
            for a in call_node.args:
                try:
                    pos_vals.append(ast.literal_eval(a))
                except Exception:
                    pos_vals.append(getattr(a, "id", None) or str(a))
            if pos_vals and len(call_node.keywords) == 0:
                result["__positional__"] = pos_vals

        return result
    except Exception:
        return {}


def repair_and_extract_tool_calls(text: str, available_tools: Dict[str, Any]) -> List[ToolCall]:
    """
    Extracts tool calls from raw LLM text when native tool calls weren't emitted
    or when a fallback model produced plain text calls.
    Supports:
      - `ACTION: tool_name {"arg": "val"}`
      - `ACTION: tool_name("val")` or `ACTION: tool_name(arg="val")`
      - Markdown json code blocks
      - `<tool_call>` XML formats
    """
    calls: List[ToolCall] = []
    if not text:
        return calls

    # 1. Check for standard ACTION: pattern
    action_matches = re.finditer(r"ACTION:\s*`?([a-zA-Z0-9_]+)`?\s*([({<].*?)?(?=(?:ACTION:|\Z))", text, re.DOTALL | re.IGNORECASE)
    for m in action_matches:
        tool_name = m.group(1).strip()
        raw_tail = (m.group(2) or "").strip()

        if tool_name not in available_tools:
            continue

        args_dict: Dict[str, Any] = {}
        if raw_tail.startswith("{") and "}" in raw_tail:
            end_idx = raw_tail.rfind("}")
            json_str = raw_tail[:end_idx + 1]
            try:
                args_dict = json.loads(json_str)
            except Exception:
                try:
                    args_dict = ast.literal_eval(json_str)
                except Exception:
                    pass

        elif raw_tail.startswith("(") and ")" in raw_tail:
            end_idx = raw_tail.rfind(")")
            sig_str = raw_tail[:end_idx + 1]
            parsed = parse_python_call_args(sig_str)
            if "__positional__" in parsed:
                fn = available_tools.get(tool_name)
                import inspect
                try:
                    params = [p for p in inspect.signature(fn).parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)]
                    for idx, val in enumerate(parsed["__positional__"]):
                        if idx < len(params):
                            args_dict[params[idx].name] = val
                except Exception:
                    pass
            else:
                args_dict = parsed

        elif "<arg_key>" in raw_tail:
            keys = re.findall(r"<arg_key>(.*?)</arg_key>", raw_tail)
            vals = re.findall(r"<arg_value>(.*?)</arg_value>", raw_tail)
            for k, v in zip(keys, vals):
                args_dict[k.strip()] = v.strip()

        calls.append(ToolCall(tool_name, args_dict))

    if calls:
        return calls

    # 2. Check for fenced JSON tool call blocks
    code_blocks = re.findall(r"```(?:json)?\s*(\{\s*\"(?:action|tool|name)\"\s*:.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    for cb in code_blocks:
        try:
            data = json.loads(cb)
            t_name = data.get("name") or data.get("tool") or data.get("action")
            if t_name in available_tools:
                args = data.get("parameters") or data.get("arguments") or data.get("args") or {}
                calls.append(ToolCall(t_name, args))
        except Exception:
            pass

    return calls


# --------------------------------------------------------------------------- #
# Gateway Provider Calls
# --------------------------------------------------------------------------- #
def _call_groq(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    model: str = PRIMARY_MODEL,
    temperature: float = 0.2,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> UnifiedMessage:
    from groq import Groq
    # max_retries=0 prevents hidden 60s retry hangs on rate-limits
    client = Groq(api_key=GROQ_API_KEY, timeout=TIMEOUT, max_retries=0)

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    if stream_callback and not tools:
        kwargs["stream"] = True
        stream = client.chat.completions.create(**kwargs)
        collected_content = []
        for chunk in stream:
            content_piece = chunk.choices[0].delta.content or ""
            if content_piece:
                collected_content.append(content_piece)
                stream_callback(content_piece)
        return UnifiedMessage(content="".join(collected_content), tool_calls=[], provider="groq")

    res = client.chat.completions.create(**kwargs)
    msg = res.choices[0].message
    content = msg.content or ""
    tool_calls: List[ToolCall] = []

    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append(ToolCall(tc.function.name, tc.function.arguments))

    return UnifiedMessage(content=content, tool_calls=tool_calls, provider="groq")


def _call_gemini(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    model: str = GEMINI_MODEL,
    temperature: float = 0.2,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> UnifiedMessage:
    """Invokes Google Gemini via official google-genai SDK (with tool support)."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    contents = []
    system_parts: List[str] = []
    pending_tool_parts: List[Any] = []

    def _flush_tool_parts():
        # Gemini wants all responses to one model turn's function calls in a SINGLE user content.
        if pending_tool_parts:
            contents.append(types.Content(role="user", parts=list(pending_tool_parts)))
            pending_tool_parts.clear()

    for m in messages:
        role = m.get("role")
        text = m.get("content") or ""
        if role == "system":
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            pending_tool_parts.append(
                types.Part.from_function_response(
                    name=m.get("name", "tool"),
                    response={"result": text},
                )
            )
            continue
        _flush_tool_parts()
        if role == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=text or " ")]))
        elif role == "assistant":
            parts = [types.Part.from_text(text=text)] if text else []
            if m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    parts.append(types.Part.from_function_call(name=fn.get("name", ""), args=args))
            if parts:
                contents.append(types.Content(role="model", parts=parts))
    _flush_tool_parts()
    system_instruction = "\n\n".join(system_parts) if system_parts else None

    config_args: Dict[str, Any] = {"temperature": temperature}
    if system_instruction:
        config_args["system_instruction"] = system_instruction

    if tools:
        decls = []
        for t in tools:
            fn = t.get("function", {})
            decls.append(types.FunctionDeclaration(
                name=fn.get("name", ""),
                description=fn.get("description", ""),
                parameters=fn.get("parameters", {"type": "object", "properties": {}}),
            ))
        config_args["tools"] = [types.Tool(function_declarations=decls)]
        config_args["tool_config"] = types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="AUTO")
        )

    config = types.GenerateContentConfig(**config_args)

    if stream_callback and not tools:
        response_stream = client.models.generate_content_stream(model=model, contents=contents, config=config)
        collected_content = []
        for chunk in response_stream:
            chunk_text = chunk.text or ""
            if chunk_text:
                collected_content.append(chunk_text)
                stream_callback(chunk_text)
        return UnifiedMessage(content="".join(collected_content), tool_calls=[], provider="gemini")

    response = client.models.generate_content(model=model, contents=contents, config=config)

    # Extract native function calls if emitted.
    tool_calls: List[ToolCall] = []
    text_parts: List[str] = []
    for cand in (response.candidates or []):
        if not cand.content:
            continue
        for part in cand.content.parts:
            fc = getattr(part, "function_call", None)
            if fc:
                tool_calls.append(ToolCall(fc.name, dict(fc.args or {})))
            else:
                txt = getattr(part, "text", None)
                if txt:
                    text_parts.append(txt)

    return UnifiedMessage(
        content="".join(text_parts),
        tool_calls=tool_calls,
        provider="gemini",
    )


def _call_openrouter(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    model: str = OPENROUTER_MODEL,
    temperature: float = 0.2,
) -> UnifiedMessage:
    from openai import OpenAI
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY, timeout=TIMEOUT)

    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if tools:
        kwargs["tools"] = tools

    res = client.chat.completions.create(**kwargs)
    msg = res.choices[0].message
    content = msg.content or ""
    tool_calls: List[ToolCall] = []

    if hasattr(msg, "tool_calls") and msg.tool_calls:
        for tc in msg.tool_calls:
            tool_calls.append(ToolCall(tc.function.name, tc.function.arguments))

    return UnifiedMessage(content=content, tool_calls=tool_calls, provider="openrouter")


def _call_local(messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]], temperature: float = 0.2) -> UnifiedMessage:
    from openai import OpenAI
    client = OpenAI(base_url=LOCAL_LLM_URL, api_key="local-token", timeout=TIMEOUT, max_retries=0)

    model_name = LOCAL_LLM_MODEL
    if not model_name:
        try:
            listed = client.models.list().data
            model_name = listed[0].id if listed else "local-model"
        except Exception:
            model_name = "local-model"

    res = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        max_tokens=2048,
    )
    content = res.choices[0].message.content or ""
    return UnifiedMessage(content=content, tool_calls=[], provider="local")



def ask_ai_from_provider(provider: str, messages: List[Dict[str, Any]], temperature: float = 0.2) -> UnifiedMessage:
    """Call one provider only; no fallback and no shared response cache."""
    provider = (provider or "").strip().casefold()
    clean_messages = _sanitize_messages(messages)
    if provider == "groq":
        if not GROQ_API_KEY:
            raise RuntimeError("Groq is not configured")
        return _call_groq(clean_messages, None, model=PRIMARY_MODEL, temperature=temperature)
    if provider == "gemini":
        if not GEMINI_API_KEY:
            raise RuntimeError("Gemini is not configured")
        return _call_gemini(clean_messages, None, model=GEMINI_MODEL, temperature=temperature)
    if provider == "openrouter":
        if not OPENROUTER_API_KEY:
            raise RuntimeError("OpenRouter is not configured")
        return _call_openrouter(clean_messages, None, model=OPENROUTER_MODEL, temperature=temperature)
    if provider == "local":
        return _call_local(clean_messages, None, temperature=temperature)
    raise ValueError(f"Unsupported provider: {provider}")


def _discover_gemini_model() -> Optional[str]:
    """Ask the API which Flash models this key can use and pick the newest stable one."""
    try:
        from google import genai
        client = genai.Client(api_key=GEMINI_API_KEY)
        names: List[str] = []
        for m in client.models.list():
            name = (getattr(m, "name", "") or "").replace("models/", "")
            if "flash" not in name:
                continue
            if any(bad in name for bad in ("image", "tts", "live", "embed", "audio", "lite", "-exp", "preview")):
                continue
            actions = getattr(m, "supported_actions", None) or getattr(m, "supported_generation_methods", None)
            if actions and "generateContent" not in actions:
                continue
            names.append(name)
        return sorted(names, reverse=True)[0] if names else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Master Router
# --------------------------------------------------------------------------- #
def ask_ai(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    available_tools_dict: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
    use_cache: bool = True,
    stream_callback: Optional[Callable[[str], None]] = None,
) -> UnifiedMessage:
    """
    Multi-tier resilient dispatcher with 60-second in-memory response caching:
      Tier 1: Groq (ultra fast primary)
      Tier 2: Gemini 3.8 Flash (deep context reasoning fallback)
      Tier 3: OpenRouter (high capability fallback)
      Tier 4: Local LLM
    """
    global _GEMINI_MODEL_OVERRIDE

    # Always send a protocol-valid history (fixes "tool_calls must be followed by tool messages").
    messages = _sanitize_messages(messages)

    # 0. Check TTL Cache
    cache_key = _compute_cache_key(messages, tools, temperature) if use_cache else ""
    if use_cache and cache_key:
        cached = _get_cached_response(cache_key)
        if cached:
            if stream_callback and cached.content:
                stream_callback(cached.content)
            return cached

    errors = []

    # 0.5. LOCAL-ONLY PRIVACY MODE — never touch the cloud
    import os as _os_gw
    if _os_gw.getenv("BERU_PRIVACY_MODE", "").lower() == "local_only":
        try:
            msg = _call_local(messages, tools, temperature=temperature)
            if not msg.tool_calls and available_tools_dict:
                recovered = repair_and_extract_tool_calls(msg.content, available_tools_dict)
                if recovered:
                    msg.tool_calls = recovered
            if use_cache and cache_key:
                _set_cached_response(cache_key, msg)
            return msg
        except Exception as e:
            return UnifiedMessage(
                content=f"⚠️ Local-only mode is enabled, but the local LLM failed: {e}",
                tool_calls=[],
                provider="local_error",
            )

    # 1. Try Groq: primary model, then backup model (on ANY failure, incl. model-not-found / rate-limit)
    if GROQ_API_KEY:
        groq_chain: List[str] = []
        for mdl in (PRIMARY_MODEL, GROQ_BACKUP_MODEL):
            if mdl and mdl not in groq_chain and mdl not in _DEAD_GROQ_MODELS:
                groq_chain.append(mdl)
        for idx, mdl in enumerate(groq_chain):
            try:
                msg = _call_groq(messages, tools, model=mdl, temperature=temperature, stream_callback=stream_callback)
                if use_cache and cache_key:
                    _set_cached_response(cache_key, msg)
                return msg
            except Exception as e:
                err_msg = str(e)
                label = "primary" if idx == 0 else "backup"
                errors.append(f"Groq {label} error ({mdl}): {err_msg}")
                if _is_model_missing_error(err_msg):
                    _DEAD_GROQ_MODELS.add(mdl)
                elif "429" in err_msg or "rate_limit" in err_msg.lower():
                    time.sleep(0.5)

    # 2. Try Gemini (auto-discovers a working Flash model if the configured one is gone)
    if GEMINI_API_KEY:
        gem_model = _GEMINI_MODEL_OVERRIDE or GEMINI_MODEL
        for attempt in range(2):
            try:
                msg = _call_gemini(messages, tools, model=gem_model, temperature=temperature, stream_callback=stream_callback)
                if not msg.tool_calls and available_tools_dict:
                    recovered = repair_and_extract_tool_calls(msg.content, available_tools_dict)
                    if recovered:
                        msg.tool_calls = recovered
                if use_cache and cache_key:
                    _set_cached_response(cache_key, msg)
                return msg
            except Exception as e:
                errors.append(f"Gemini error ({gem_model}): {e}")
                if attempt == 0 and _is_model_missing_error(str(e)):
                    alt = _discover_gemini_model()
                    if alt and alt != gem_model:
                        _GEMINI_MODEL_OVERRIDE = alt
                        gem_model = alt
                        continue
                break

    # 3. Try OpenRouter
    if OPENROUTER_API_KEY:
        try:
            msg = _call_openrouter(messages, tools, temperature=temperature)
            if not msg.tool_calls and available_tools_dict:
                recovered = repair_and_extract_tool_calls(msg.content, available_tools_dict)
                if recovered:
                    msg.tool_calls = recovered
            if use_cache and cache_key:
                _set_cached_response(cache_key, msg)
            return msg
        except Exception as e:
            errors.append(f"OpenRouter error: {e}")

    # 4. Try Local LLM
    try:
        msg = _call_local(messages, tools, temperature=temperature)
        if not msg.tool_calls and available_tools_dict:
            recovered = repair_and_extract_tool_calls(msg.content, available_tools_dict)
            if recovered:
                msg.tool_calls = recovered
        if use_cache and cache_key:
            _set_cached_response(cache_key, msg)
        return msg
    except Exception as e:
        errors.append(f"Local LLM error: {e}")

    # All tiers failed - return a graceful UnifiedMessage instead of raising an unhandled exception
    # Classify the failure so the user (and the agent) sees the truth.
    if any("model_not_found" in e.lower() or "does not exist" in e.lower() or "404" in e for e in errors):
        headline = "⚠️ All AI providers failed — one or more MODEL IDs are invalid (not a rate-limit issue)."
    elif any("429" in e or "rate_limit" in e.lower() or "quota" in e.lower() for e in errors):
        headline = "⚠️ All AI providers failed — at least one returned 429/rate-limit. Others may also be down."
    elif any("api_key" in e.lower() or "unauthorized" in e.lower() or "401" in e for e in errors):
        headline = "⚠️ All AI providers failed — authentication rejected. Check .env keys."
    else:
        headline = "⚠️ All AI providers failed — network/config issue (not necessarily rate-limit)."

    return UnifiedMessage(
        content=(
            headline + "\n\nPer-provider errors:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + "\n\nFix steps: (1) verify GEMINI_MODEL / PRIMARY_MODEL exist for your key, "
              "(2) check .env keys, (3) confirm internet, (4) restart the app."
        ),
        tool_calls=[],
        provider="fallback_error",
    )


async def async_ask_ai(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    available_tools_dict: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
) -> UnifiedMessage:
    """Async wrapper around ask_ai to run non-blockingly."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, ask_ai, messages, tools, available_tools_dict, temperature)
