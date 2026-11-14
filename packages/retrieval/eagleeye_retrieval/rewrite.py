"""Query rewrite: one fast-tier call → standalone question + a few variants."""

import json
import logging
import re
from typing import Any

from eagleeye_llm.gateway import ChatMessage, LLMGateway

logger = logging.getLogger(__name__)

MAX_QUERY_CHARS = 500
MAX_VARIANTS = 3
MAX_HISTORY_TURNS = 4

REWRITE_PROMPT = """You rewrite a user's question for document search.
Given the recent conversation and the latest question, return ONLY a JSON object:
{"standalone": "<the question rewritten to be self-contained>",
 "variants": ["<up to 3 alternative search queries: keywords, synonyms, sub-questions>"]}
No prose, no markdown fences."""

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_rewrite(raw: str, question: str) -> list[str]:
    """Defensive parse; always returns at least the original question."""
    fallback = [question[:MAX_QUERY_CHARS]]
    try:
        data = json.loads(_FENCE.sub("", raw.strip()))
    except (json.JSONDecodeError, TypeError):
        return fallback
    if not isinstance(data, dict):
        return fallback
    candidates: list[str] = []
    standalone = data.get("standalone")
    if isinstance(standalone, str):
        candidates.append(standalone)
    variants = data.get("variants")
    if isinstance(variants, list):
        candidates.extend(v for v in variants[:MAX_VARIANTS] if isinstance(v, str))

    queries: list[str] = []
    for c in candidates:
        q = c.strip()[:MAX_QUERY_CHARS]
        if q and q.lower() not in {x.lower() for x in queries}:
            queries.append(q)
    return queries or fallback


def _format_history(history: list[ChatMessage]) -> str:
    turns = [m for m in history if m.role in ("user", "assistant")][-MAX_HISTORY_TURNS:]
    return "\n".join(f"{m.role}: {m.content[:600]}" for m in turns)


async def rewrite_query(
    llm: LLMGateway, question: str, history: list[ChatMessage], cache: Any = None
) -> list[str]:
    convo = _format_history(history)
    user = f"Conversation:\n{convo or '(none)'}\n\nLatest question:\n{question[:2000]}"
    parts = (REWRITE_PROMPT, user)
    if cache is not None:
        hit = await cache.get("rewrite", parts)
        if hit is not None and isinstance(hit.get("raw"), str):
            return parse_rewrite(hit["raw"], question)
    try:
        raw, usage = await llm.complete(
            "fast",
            [
                ChatMessage(role="system", content=REWRITE_PROMPT),
                ChatMessage(role="user", content=user),
            ],
            max_tokens=300,
        )
    except Exception:
        logger.warning("query rewrite failed; using the raw question", exc_info=True)
        return [question[:MAX_QUERY_CHARS]]
    if cache is not None and not usage.degraded:
        await cache.put("rewrite", parts, {"raw": raw, "cost_usd": usage.cost_usd})
    return parse_rewrite(raw, question)
