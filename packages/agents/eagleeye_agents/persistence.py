"""Worker-side run persistence (parameterised SQL only)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

import asyncpg
from eagleeye_llm.gateway import ChatMessage

from eagleeye_agents.context import DocInfo
from eagleeye_agents.control import UsageEntry
from eagleeye_agents.steps import StepRecord

MAX_HISTORY_ROWS = 200


async def load_run(pool: asyncpg.Pool, run_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id, chat_id, user_id, status, params FROM runs WHERE id = $1", run_id
    )


async def claim_run(
    pool: asyncpg.Pool, run_id: str, model_ids: dict, prompt_versions: dict
) -> bool:
    """QUEUED → RUNNING exactly once; a redelivered task finds nothing to claim."""
    result = await pool.execute(
        """
        UPDATE runs SET status = 'RUNNING', heartbeat_at = now(), model_ids = $2,
                        prompt_versions = $3, updated_at = now()
        WHERE id = $1 AND status = 'QUEUED'
        """,
        run_id,
        model_ids,
        prompt_versions,
    )
    return result.endswith("1")


async def load_user_role(pool: asyncpg.Pool, user_id: str) -> str:
    role = await pool.fetchval(
        "SELECT role FROM users WHERE id = $1 AND status = 'active'", user_id
    )
    return str(role) if role else "member"


async def heartbeat(pool: asyncpg.Pool, run_id: str) -> None:
    await pool.execute(
        "UPDATE runs SET heartbeat_at = now() WHERE id = $1 AND status = 'RUNNING'", run_id
    )


def _text_of(parts: dict) -> str:
    return "".join(p.get("text", "") for p in parts.get("parts", []) if p.get("type") == "text")


async def load_conversation(
    pool: asyncpg.Pool, chat_id: str, run_id: str
) -> tuple[str, list[ChatMessage]]:
    """Returns (this run's user question, earlier turns oldest-first)."""
    rows = await pool.fetch(
        """
        SELECT role, parts, run_id FROM messages WHERE chat_id = $1
        ORDER BY msg_no ASC LIMIT $2
        """,
        chat_id,
        MAX_HISTORY_ROWS,
    )
    for i, row in enumerate(rows):
        if row["role"] == "user" and str(row["run_id"]) == run_id:
            history = [ChatMessage(r["role"], _text_of(r["parts"])) for r in rows[:i]]
            return _text_of(row["parts"]), history
    raise LookupError(f"no user message for run {run_id}")


async def insert_assistant_message(
    pool: asyncpg.Pool,
    chat_id: str,
    run_id: str,
    parts: list[dict],
    tokens_in: int,
    tokens_out: int,
) -> str:
    async with pool.acquire() as conn, conn.transaction():
        msg_no = await conn.fetchval(
            """
            UPDATE chats SET last_message_no = last_message_no + 1, updated_at = now()
            WHERE id = $1 RETURNING last_message_no
            """,
            chat_id,
        )
        message_id = await conn.fetchval(
            """
            INSERT INTO messages (chat_id, msg_no, role, parts, run_id, tokens_in, tokens_out)
            VALUES ($1, $2, 'assistant', $3, $4, $5, $6) RETURNING id
            """,
            chat_id,
            msg_no,
            {"parts": parts},
            run_id,
            tokens_in,
            tokens_out,
        )
    return str(message_id)


async def finish_run(
    pool: asyncpg.Pool,
    run_id: str,
    *,
    status: str,
    route: str | None,
    guard: dict | None,
    degraded: bool,
    usage: dict,
    cost_usd: float,
    error_code: str | None = None,
    first_token_at: datetime | None = None,
    warnings: Sequence[str] = (),
) -> None:
    await pool.execute(
        """
        UPDATE runs SET status = $2, route = $3, guard = $4, degraded = $5, usage = $6,
                        cost_usd = $7, error_code = $8, first_token_at = $9,
                        warnings = $10, finished_at = now(), updated_at = now()
        WHERE id = $1
        """,
        run_id,
        status,
        route,
        guard,
        degraded,
        usage,
        cost_usd,
        error_code,
        first_token_at,
        list(dict.fromkeys(warnings)),
    )


async def insert_steps(pool: asyncpg.Pool, run_id: str, records: Sequence[StepRecord]) -> None:
    if not records:
        return
    await pool.executemany(
        """
        INSERT INTO run_steps (id, run_id, parent_step_id, seq, kind, name, input, output_summary,
                               status, duration_ms, tokens_in, tokens_out, cost_usd)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        """,
        [
            (
                r.id,
                run_id,
                r.parent_id,
                r.seq,
                r.kind,
                r.name,
                {"summary": r.input_summary},
                r.output_summary,
                r.status,
                r.duration_ms,
                r.tokens_in,
                r.tokens_out,
                r.cost_usd,
            )
            for r in records
        ],
    )


async def insert_usage(
    pool: asyncpg.Pool, user_id: str, run_id: str, entries: Sequence[UsageEntry]
) -> None:
    if not entries:
        return
    await pool.executemany(
        """
        INSERT INTO usage_ledger
            (user_id, run_id, model_id, tokens_in, tokens_out, cost_usd, cached_tokens)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        [
            (user_id, run_id, e.model_id, e.tokens_in, e.tokens_out, e.cost_usd, e.cached_tokens)
            for e in entries
        ],
    )


async def rename_chat(pool: asyncpg.Pool, chat_id: str, user_id: str, title: str) -> bool:
    result = await pool.execute(
        "UPDATE chats SET title = $3, updated_at = now() WHERE id = $1 AND user_id = $2",
        chat_id,
        user_id,
        title,
    )
    return result.endswith("1")


class PgRunStore:
    """RunStore backed by Postgres. Visibility rule mirrors eagleeye_retrieval.access."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def visible_ready_documents(self, user_id: str) -> list[DocInfo]:
        rows = await self._pool.fetch(
            """
            SELECT id, title, scope, page_count, chunk_count FROM documents
            WHERE status = 'READY' AND (scope = 'enterprise' OR owner_id = $1::uuid)
            ORDER BY created_at DESC LIMIT 100
            """,
            user_id,
        )
        return [
            DocInfo(str(r["id"]), r["title"], r["scope"], r["page_count"], r["chunk_count"])
            for r in rows
        ]

    async def record_security_event(
        self, user_id: str, run_id: str, kind: str, category: str, detail: dict[str, Any]
    ) -> None:
        await self._pool.execute(
            """
            INSERT INTO security_events (user_id, run_id, kind, category, detail)
            VALUES ($1, $2, $3, $4, $5)
            """,
            user_id,
            run_id,
            kind,
            category,
            detail,
        )
