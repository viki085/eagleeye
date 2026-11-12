import logging

import asyncpg
import redis.asyncio as aioredis
from eagleeye_core.config import get_settings
from eagleeye_llm.gateway import ChatMessage, LLMGateway, Usage
from eagleeye_retrieval.service import Retriever

from app.events import EventSink
from app.repos import messages as messages_repo
from app.repos import runs as runs_repo
from app.repos.chats import rename_chat
from app.services.citations import Citation, extract
from app.services.grounding import Grounding, ground
from app.services.rag_prompt import grounded_system_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are EagleEye, an enterprise AI assistant. Answer clearly and concisely. "
    "Use markdown formatting where it improves readability."
)
MAX_HISTORY_MESSAGES = 20
REWRITE_HISTORY_MESSAGES = 4
TITLE_PROMPT = (
    "Generate a short title (max 5 words, no quotes, no trailing punctuation) "
    "for a conversation that starts with this message:"
)


def _text_of(row: asyncpg.Record) -> str:
    return "".join(p.get("text", "") for p in row["parts"]["parts"] if p.get("type") == "text")


def _to_messages(rows: list[asyncpg.Record]) -> list[ChatMessage]:
    return [ChatMessage(role=r["role"], content=_text_of(r)) for r in rows]


def build_prompt(rows: list[asyncpg.Record], grounding: Grounding | None) -> list[ChatMessage]:
    system = (
        grounded_system_prompt(grounding.chunks)
        if grounding is not None
        else ChatMessage(role="system", content=SYSTEM_PROMPT)
    )
    return [system, *_to_messages(rows[-MAX_HISTORY_MESSAGES:])]


async def _ground_for_run(
    pool: asyncpg.Pool,
    retriever: Retriever | None,
    sink: EventSink,
    run_id: str,
    user_id: str,
    history: list[asyncpg.Record],
) -> Grounding | None:
    if not history or history[-1]["role"] != "user":
        return None
    params = await runs_repo.get_params(pool, run_id)
    doc_ids = [str(d) for d in params.get("doc_ids", [])]
    prior = _to_messages(history[:-1])[-REWRITE_HISTORY_MESSAGES:]
    return await ground(pool, retriever, sink, _text_of(history[-1]), prior, user_id, doc_ids)


async def _stream_answer(
    llm: LLMGateway, sink: EventSink, prompt: list[ChatMessage]
) -> tuple[str, Usage]:
    chunks: list[str] = []
    usage = Usage()
    async for chunk in llm.stream("capable", prompt):
        if chunk.done:
            usage = chunk.usage
        elif chunk.text:
            chunks.append(chunk.text)
            await sink.emit("text.delta", {"text": chunk.text})
    return "".join(chunks), usage


async def _persist_answer(
    pool: asyncpg.Pool,
    chat_id: str,
    run_id: str,
    answer: str,
    citations: list[Citation],
    usage: Usage,
) -> asyncpg.Record:
    parts: list[dict] = [{"type": "text", "text": answer}]
    if citations:
        parts.append({"type": "citations", "items": [c.to_dict() for c in citations]})
    async with pool.acquire() as conn, conn.transaction():
        return await messages_repo.insert_assistant_message(
            conn, chat_id, parts, run_id, usage.tokens_in, usage.tokens_out
        )


async def execute_run(
    pool: asyncpg.Pool,
    redis: aioredis.Redis,
    llm: LLMGateway,
    run_id: str,
    chat_id: str,
    user_id: str,
    retriever: Retriever | None = None,
) -> None:
    """Phase 2 path: (optional retrieval) → capable-class stream → citations → persist.

    Runs as an in-process async task; moves to the Celery agent-worker in Phase 3.
    """
    sink = EventSink(redis, run_id)
    try:
        await runs_repo.mark_running(pool, run_id, {"capable": get_settings().model_capable})
        await sink.emit("run.started", {"run_id": run_id, "model_tier": "capable"})

        history = await messages_repo.list_messages(pool, chat_id)
        grounding = await _ground_for_run(pool, retriever, sink, run_id, user_id, history)
        answer, usage = await _stream_answer(llm, sink, build_prompt(history, grounding))

        citations = extract(answer, grounding.chunks) if grounding is not None else []
        for citation in citations:
            await sink.emit("citation", citation.to_dict())

        message = await _persist_answer(pool, chat_id, run_id, answer, citations, usage)
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
                "usage": {"in": usage.tokens_in, "out": usage.tokens_out, "cost": usage.cost_usd},
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
    first_text = _text_of(user_messages[0])
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
