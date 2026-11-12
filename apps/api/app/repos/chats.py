import asyncpg


async def list_chats(pool: asyncpg.Pool, user_id: str, limit: int = 50) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT id, title, archived, created_at, updated_at
        FROM chats WHERE user_id = $1 AND NOT archived
        ORDER BY updated_at DESC LIMIT $2
        """,
        user_id,
        limit,
    )


async def create_chat(pool: asyncpg.Pool, user_id: str) -> asyncpg.Record:
    return await pool.fetchrow(
        "INSERT INTO chats (user_id) VALUES ($1) RETURNING id, title, created_at, updated_at",
        user_id,
    )


async def get_owned_chat(pool: asyncpg.Pool, chat_id: str, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM chats WHERE id = $1 AND user_id = $2", chat_id, user_id
    )


async def rename_chat(pool: asyncpg.Pool, chat_id: str, user_id: str, title: str) -> bool:
    result = await pool.execute(
        "UPDATE chats SET title = $3, updated_at = now() WHERE id = $1 AND user_id = $2",
        chat_id,
        user_id,
        title,
    )
    return result.endswith("1")


async def delete_chat(pool: asyncpg.Pool, chat_id: str, user_id: str) -> bool:
    result = await pool.execute(
        "DELETE FROM chats WHERE id = $1 AND user_id = $2", chat_id, user_id
    )
    return result.endswith("1")


async def next_msg_no(conn: asyncpg.Connection, chat_id: str) -> int:
    return await conn.fetchval(
        """
        UPDATE chats SET last_message_no = last_message_no + 1, updated_at = now()
        WHERE id = $1 RETURNING last_message_no
        """,
        chat_id,
    )
