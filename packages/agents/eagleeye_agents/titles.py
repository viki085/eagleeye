"""First-turn chat title (fast tier). Failures are logged and ignored."""

import logging

import asyncpg
from eagleeye_llm.gateway import ChatMessage, LLMGateway

from eagleeye_agents import persistence

logger = logging.getLogger(__name__)

TITLE_PROMPT = (
    "Generate a short title (max 5 words, no quotes, no trailing punctuation) "
    "for a conversation that starts with this message:"
)
MAX_TITLE_CHARS = 80


async def maybe_title(
    pool: asyncpg.Pool,
    llm: LLMGateway,
    chat_id: str,
    user_id: str,
    question: str,
    history: list[ChatMessage],
) -> str | None:
    if any(m.role == "user" for m in history):
        return None  # not the first turn
    try:
        title, _ = await llm.complete(
            "fast", [ChatMessage("user", f"{TITLE_PROMPT}\n\n{question[:500]}")], max_tokens=24
        )
        title = title.strip().strip('"')[:MAX_TITLE_CHARS]
        if title and await persistence.rename_chat(pool, chat_id, user_id, title):
            return title
    except Exception:
        logger.warning("title generation failed for chat %s", chat_id, exc_info=True)
    return None
