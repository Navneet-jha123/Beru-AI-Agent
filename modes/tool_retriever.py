"""
modes/tool_retriever.py - Per-request tool retrieval.

Called once per request from agent.run_agent. Returns the exact list of tool
schemas to send to the LLM.

Flow:
    1. classify_bundles(message, mode) -> [bundle names]
    2. Collect all schema names in those bundles.
    3. Rank schemas by keyword relevance to the message.
    4. Return top_k schemas.

This file is the swap point. To upgrade to BM25 or vector retrieval later,
replace `_rank_by_keyword` with a new implementation. The interface
`retrieve_tools(message, mode, top_k)` stays identical, so agent.py never
needs to change again.

Fallback behavior: if classification or ranking returns fewer than MIN_SCHEMAS
schemas, we fall back to "all core" schemas to guarantee the LLM always has a
useful toolbox. This means worst case we send ~30 tools instead of 20 — still
under the 128 limit, still correct.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from modes.tools_bundles import TOOL_BUNDLES, classify_bundles

MIN_SCHEMAS = 8  # If ranking returns fewer than this, expand to core bundle.


def _tokenize(text: str) -> set:
    return set(re.findall(r"[a-z][a-z0-9_]+", (text or "").lower()))


def _schema_name(schema: Dict[str, Any]) -> str:
    return (schema.get("function") or {}).get("name", "")


def _score_schema(schema: Dict[str, Any], tokens: set) -> int:
    """
    Cheap keyword-relevance score. Higher is better.

    Scoring:
      +3 for each match on the tool's name (strong signal)
      +1 for each match on the tool's description
    """
    fn = schema.get("function") or {}
    name = (fn.get("name") or "").lower()
    desc = (fn.get("description") or "").lower()
    name_tokens = _tokenize(name.replace("_", " "))
    desc_tokens = _tokenize(desc)
    score = 3 * len(tokens & name_tokens) + len(tokens & desc_tokens)
    return score


def _rank_by_keyword(
    schemas: List[Dict[str, Any]],
    message: str,
    top_k: int,
) -> List[Dict[str, Any]]:
    """Rank by keyword relevance to the message; ties broken by name for stability."""
    tokens = _tokenize(message)
    if not tokens:
        # No meaningful tokens — return first top_k for determinism.
        return schemas[:top_k]
    scored = [(_score_schema(s, tokens), _schema_name(s), s) for s in schemas]
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s for _, _, s in scored[:top_k]]


def retrieve_tools(
    message: str,
    mode: str = "General",
    top_k: int = 20,
    all_schemas: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    Return the schemas to send to the LLM for this request.

    Args:
        message: the user's current message
        mode: active persona (General / Developer / Tester / Hacker)
        top_k: cap on number of schemas returned (default 20, hard max 40)
        all_schemas: pre-loaded full schema list (defaults to tools_registry)

    Returns: List of OpenAI-style tool schema dicts, guaranteed <= top_k.
    """
    top_k = max(5, min(int(top_k), 40))

    if all_schemas is None:
        # Lazy import to avoid circular dependency
        from tools_registry import get_live_schemas
        all_schemas = get_live_schemas()

    if not all_schemas:
        return []

    # Safety net: if we're under the tool budget already, just send everything.
    if len(all_schemas) <= top_k:
        return list(all_schemas)

    # Step 1: classify into bundles.
    bundles = classify_bundles(message, mode)

    # Step 2: collect schema names allowed by those bundles.
    allowed_names: set = set()
    for b in bundles:
        allowed_names.update(TOOL_BUNDLES.get(b, []))

    # These operation-specific tools are generated dynamically after an OpenAPI
    # spec is ingested. Keep them out of every unrelated request's schema set.
    if "api" in bundles:
        allowed_names.update(
            _schema_name(s) for s in all_schemas
            if _schema_name(s).startswith("apiop_")
        )

    # Always include any forged tools (user-created, must remain reachable).
    try:
        from forge import FORGED_SCHEMAS
        for fs in FORGED_SCHEMAS:
            n = _schema_name(fs)
            if n:
                allowed_names.add(n)
    except Exception:
        pass

    # Step 3: filter to those schemas.
    candidate_schemas = [s for s in all_schemas if _schema_name(s) in allowed_names]

    # Step 4: rank within candidate set.
    ranked = _rank_by_keyword(candidate_schemas, message, top_k)

    # Step 5: fallback if we came up short.
    if len(ranked) < MIN_SCHEMAS:
        core_names = set(TOOL_BUNDLES.get("core", []))
        core_schemas = [s for s in all_schemas if _schema_name(s) in core_names]
        merged = {_schema_name(s): s for s in ranked}
        for s in core_schemas:
            merged.setdefault(_schema_name(s), s)
        ranked = list(merged.values())[:top_k]

    return ranked
