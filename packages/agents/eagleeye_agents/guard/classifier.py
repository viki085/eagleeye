"""LLM guard: one fast-tier JSON call, strictly parsed, one retry, then fail closed."""

import json
import logging
from collections.abc import Sequence
from typing import Any

from eagleeye_llm.gateway import ChatMessage, LLMGateway, Usage
from pydantic import BaseModel, ValidationError

from eagleeye_agents.errors import GuardUnavailableError
from eagleeye_agents.guard.verdict import Complexity, GuardVerdict, Intent, Safety

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2
MAX_TITLES = 20
MAX_TURN_CHARS = 400


class _GuardJson(BaseModel):
    safe: Safety
    intent: Intent
    complexity: Complexity


def parse_verdict(raw: str) -> GuardVerdict:
    data = _GuardJson.model_validate(json.loads(raw))
    return GuardVerdict(data.safe, data.intent, data.complexity, "llm")


def build_user_message(
    question: str, history: Sequence[ChatMessage], doc_titles: Sequence[str], has_selection: bool
) -> str:
    turns = [m for m in history if m.role in ("user", "assistant")][-2:]
    convo = "\n".join(f"{m.role}: {m.content[:MAX_TURN_CHARS]}" for m in turns) or "(none)"
    titles = ", ".join(t[:80] for t in doc_titles[:MAX_TITLES]) or "(none)"
    selection = "yes" if has_selection else "no"
    return (
        f"User's documents: {titles}\nDocuments selected for this question: {selection}\n\n"
        f"Earlier turns:\n{convo}\n\n<latest_message>\n{question}\n</latest_message>"
    )


async def classify(
    llm: LLMGateway,
    system_prompt: str,
    question: str,
    history: Sequence[ChatMessage],
    doc_titles: Sequence[str],
    has_selection: bool,
    cache: Any = None,  # eagleeye_core.app_cache.AppCache
) -> tuple[GuardVerdict, Usage]:
    user = build_user_message(question, history, doc_titles, has_selection)
    messages = [ChatMessage("system", system_prompt), ChatMessage("user", user)]
    parts = (system_prompt, user)  # the verdict depends only on exactly this input
    if cache is not None:
        hit = await cache.get("guard", parts)
        if hit is not None:
            try:
                return parse_verdict(hit["raw"]), Usage()
            except (KeyError, json.JSONDecodeError, ValidationError, TypeError):
                logger.warning("ignoring an unreadable cached guard verdict")
    last_error: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            raw, usage = await llm.complete(
                "fast", messages, max_tokens=120, json_mode=True, temperature=0
            )
            verdict = parse_verdict(raw)
            if cache is not None and not usage.degraded:
                await cache.put("guard", parts, {"raw": raw, "cost_usd": usage.cost_usd})
            return verdict, usage
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("guard returned invalid JSON (attempt %d)", attempt + 1)
            last_error = exc
        except Exception as exc:  # provider down etc. — fail closed below
            logger.warning("guard call failed (attempt %d)", attempt + 1, exc_info=True)
            last_error = exc
    raise GuardUnavailableError(type(last_error).__name__ if last_error else "unknown")
