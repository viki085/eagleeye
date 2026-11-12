import asyncpg

from app.repos.chats import next_msg_no


async def list_messages(
    pool: asyncpg.Pool, chat_id: str, limit: int = 200
) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT id, msg_no, role, parts, run_id, created_at
        FROM messages WHERE chat_id = $1 ORDER BY msg_no ASC LIMIT $2
        """,
        chat_id,
        limit,
    )


async def find_by_idempotency_key(
    pool: asyncpg.Pool, chat_id: str, key: str
) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT id, run_id FROM messages WHERE chat_id = $1 AND idempotency_key = $2",
        chat_id,
        key,
    )


async def insert_user_message(
    conn: asyncpg.Connection, chat_id: str, text: str, run_id: str, idempotency_key: str
) -> asyncpg.Record:
    msg_no = await next_msg_no(conn, chat_id)
    return await conn.fetchrow(
        """
        INSERT INTO messages (chat_id, msg_no, role, parts, run_id, idempotency_key)
        VALUES ($1, $2, 'user', $3, $4, $5)
        RETURNING id, msg_no
        """,
        chat_id,
        msg_no,
        {"parts": [{"type": "text", "text": text}]},
        run_id,
        idempotency_key,
    )
