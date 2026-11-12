import logging

import asyncpg
import redis.asyncio as aioredis

from eagleeye_core.config import get_settings
from eagleeye_llm.gateway import ChatMessage, LLMGateway, Usage

from app.events import EventSink
from app.repos import messages as messages_repo
from app.repos import runs as runs_repo
from app.repos.chats import rename_chat

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are EagleEye, an enterprise AI assistant. Answer clearly and concisely. "
    "Use markdown formatting where it improves readability."
)
MAX_HISTORY_MESSAGES = 20
TITLE_PROMPT = (
    "Generate a short title (max 5 words, no quotes, no trailing punctuation) "
    "for a conversation that starts with this message:"
)


def _history_to_prompt(rows: list[asyncpg.Record]) -> list[ChatMessage]:
    prompt = [ChatMessage(role="system", content=SYSTEM_PROMPT)]
    for row in rows[-MAX_HISTORY_MESSAGES:]:
        text = "".join(
            p.get("text", "") for p in row["parts"]["parts"] if p.get("type") == "text"
        )
        prompt.append(ChatMessage(role=row["role"], content=text))
    return prompt


async def execute_run(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    llm: LLMGateway,
    run_id: str,
    chat_id: str,
    user_id: str,
) -> None:
    """Phase 1 single-LLM path: history → capable-class stream → persist.

    Runs as an in-process async task; moves to the Celery agent-worker in Phase 3.
    """
    sink = EventSink(redis, run_id)
    settings = get_settings()
    try:
        await runs_repo.mark_running(pool, run_id, {"capable": settings.model_capable})
        await sink.emit("run.started", {"run_id": run_id, "model_tier": "capable"})

        history = await messages_repo.list_messages(pool, chat_id)
        prompt = _history_to_prompt(history)

        chunks: list[str] = []
        usage = Usage()
        async for chunk in llm.stream("capable", prompt):
            if chunk.done:
                usage = chunk.usage
            elif chunk.text:
                chunks.append(chunk.text)
                await sink.emit("text.delta", {"text": chunk.text})
        answer = "".join(chunks)

        async with pool.acquire() as conn, conn.transaction():
            message = await messages_repo.insert_assistant_message(
                conn, chat_id, answer, run_id, usage.tokens_in, usage.tokens_out
            )
        await runs_repo.mark_finished(
            pool,
            run_id,
            "SUCCEEDED",
            usage={"tokens_in": usage.tokens_in, "tokens_out": usage.tokens_out},
            cost_usd=usage.cost_usd,
        )

        new_title = await _maybe_generate_title(pool, llm, chat_id, user_id, history)
        if new_title is not None:
            await sink.emit("chat.updated", {"chat_id": chat_id, "title": new_title})

        await sink.emit(
            "run.done",
            {
                "message_id": str(message["id"]),
                "usage": {
                    "in": usage.tokens_in,
                    "out": usage.tokens_out,
                    "cost": usage.cost_usd,
                },
            },
        )
    except Exception:
        logger.exception("run %s failed", run_id)
        await runs_repo.mark_finished(pool, run_id, "FAILED", error_code="LLM_ERROR")
        await sink.emit(
            "run.error",
            {"code": "LLM_ERROR", "user_message": "Something went wrong answering. Try again."},
        )


async def _maybe_generate_title(
    pool: asyncpg.Pool,
    llm: LLMGateway,
    chat_id: str,
    user_id: str,
    history: list[asyncpg.Record],
) -> str | None:
    """First turn only: fast-class call names the chat."""
    user_messages = [r for r in history if r["role"] == "user"]
    if len(user_messages) != 1:
        return None
    first_text = "".join(
        p.get("text", "") for p in user_messages[0]["parts"]["parts"] if p.get("type") == "text"
    )
    try:
        title, _ = await llm.complete(
            "fast",
            [ChatMessage(role="user", content=f"{TITLE_PROMPT}\n\n{first_text[:500]}")],
            max_tokens=24,
        )
        title = title.strip().strip('"')[:80]
        if title and await rename_chat(pool, chat_id, user_id, title):
            return title
    except Exception:
        logger.warning("title generation failed for chat %s", chat_id, exc_info=True)
    return None
