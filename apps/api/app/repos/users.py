"""Users. Accounts are provisioned by admins (enterprise: no self-signup); sign-in only finds
an existing account by its Clerk id. Deleted accounts keep their row (status 'deleted') so
billing and audit history stay intact."""

from typing import Any

import asyncpg

LIVE = "status <> 'deleted'"


async def touch_signed_in_user(pool: asyncpg.Pool, clerk_user_id: str) -> asyncpg.Record | None:
    """The account for this Clerk id (any status), refreshing "last seen"; None if no admin
    ever provisioned it. Runs on an auth-cache miss: at most once a minute per user."""
    return await pool.fetchrow(
        "UPDATE users SET last_seen_at = now() WHERE clerk_user_id = $1 RETURNING *",
        clerk_user_id,
    )


async def find_by_email(pool: asyncpg.Pool, email: str) -> asyncpg.Record | None:
    """Live account first; otherwise the most recent deleted one (for reactivation)."""
    return await pool.fetchrow(
        """
        SELECT * FROM users WHERE lower(email) = lower($1)
         ORDER BY (status = 'deleted'), updated_at DESC LIMIT 1
        """,
        email,
    )


async def get_user(pool: asyncpg.Pool, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(f"SELECT * FROM users WHERE id = $1 AND {LIVE}", user_id)  # noqa: S608


async def provision(
    pool: asyncpg.Pool,
    *,
    clerk_user_id: str,
    email: str,
    display_name: str | None,
    role: str,
    created_by: str,
    username: str | None = None,
    reactivate_id: str | None = None,
) -> asyncpg.Record:
    if reactivate_id:
        return await pool.fetchrow(
            """
            UPDATE users SET clerk_user_id = $2, email = $3, display_name = $4, role = $5,
                             status = 'active', created_by = $6, username = $7,
                             updated_at = now()
             WHERE id = $1 RETURNING *
            """,
            reactivate_id,
            clerk_user_id,
            email,
            display_name,
            role,
            created_by,
            username,
        )
    return await pool.fetchrow(
        """
        INSERT INTO users (clerk_user_id, email, display_name, role, created_by, username)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
        """,
        clerk_user_id,
        email,
        display_name,
        role,
        created_by,
        username,
    )


async def mark_deleted(pool: asyncpg.Pool, user_id: str) -> None:
    await pool.execute(
        "UPDATE users SET status = 'deleted', updated_at = now() WHERE id = $1", user_id
    )


async def active_admin_count(pool: asyncpg.Pool) -> int:
    return await pool.fetchval(
        "SELECT count(*) FROM users WHERE role = 'admin' AND status = 'active'"
    )


async def fresh_role(pool: asyncpg.Pool, user_id: str) -> tuple[str, str] | None:
    """(role, status) straight from the database — for admin checks, never cached."""
    row = await pool.fetchrow("SELECT role, status FROM users WHERE id = $1", user_id)
    return (row["role"], row["status"]) if row else None


def public(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    """What the console may see about an account (no Clerk id)."""
    data = dict(row)
    out = {k: data.get(k) for k in ("id", "email", "username", "display_name", "role", "status")}
    out["id"] = str(out["id"])
    for key in ("created_at", "last_seen_at"):
        value = data.get(key)
        out[key] = value.isoformat() if value is not None and hasattr(value, "isoformat") else value
    return out
