from collections.abc import Awaitable, Callable

import asyncpg


async def get_or_create_user(
    pool: asyncpg.Pool,
    clerk_user_id: str,
    fetch_profile: Callable[[str], Awaitable[tuple[str, str | None]]],
) -> asyncpg.Record:
    row = await pool.fetchrow("SELECT * FROM users WHERE clerk_user_id = $1", clerk_user_id)
    if row is not None:
        return row
    email, display_name = await fetch_profile(clerk_user_id)
    return await pool.fetchrow(
        """
        INSERT INTO users (clerk_user_id, email, display_name)
        VALUES ($1, $2, $3)
        ON CONFLICT (clerk_user_id) DO UPDATE SET email = EXCLUDED.email
        RETURNING *
        """,
        clerk_user_id,
        email,
        display_name,
    )
