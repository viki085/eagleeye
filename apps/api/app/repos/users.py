from collections.abc import Awaitable, Callable

import asyncpg


async def get_or_create_user(
    pool: asyncpg.Pool,
    clerk_user_id: str,
    fetch_profile: Callable[[str], Awaitable[tuple[str, str | None]]],
) -> asyncpg.Record:
    # a cache miss happens at most once a minute per user, so this also keeps "last seen" fresh
    row = await pool.fetchrow(
        "UPDATE users SET last_seen_at = now() WHERE clerk_user_id = $1 RETURNING *",
        clerk_user_id,
    )
    if row is not None:
        return row
    email, display_name = await fetch_profile(clerk_user_id)
    return await pool.fetchrow(
        """
        INSERT INTO users (clerk_user_id, email, display_name, last_seen_at)
        VALUES ($1, $2, $3, now())
        ON CONFLICT (clerk_user_id) DO UPDATE SET email = EXCLUDED.email, last_seen_at = now()
        RETURNING *
        """,
        clerk_user_id,
        email,
        display_name,
    )


async def fresh_role(pool: asyncpg.Pool, user_id: str) -> tuple[str, str] | None:
    """(role, status) straight from the database — for admin checks, never cached."""
    row = await pool.fetchrow("SELECT role, status FROM users WHERE id = $1", user_id)
    return (row["role"], row["status"]) if row else None
