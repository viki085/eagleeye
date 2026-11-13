import asyncpg

ACTIVE = "('QUEUED', 'RUNNING')"
RUNNING_STALE_S = 60  # no heartbeat for this long → the worker is gone
QUEUED_STALE_S = 300  # never picked up → no worker running


async def create_run(
    conn: asyncpg.Connection, chat_id: str, user_id: str, params: dict | None = None
) -> str:
    """Raises asyncpg.UniqueViolationError if the chat already has an active run."""
    return str(
        await conn.fetchval(
            """
            INSERT INTO runs (chat_id, user_id, status, params)
            VALUES ($1, $2, 'QUEUED', $3) RETURNING id
            """,
            chat_id,
            user_id,
            params or {},
        )
    )


async def get_owned_run(pool: asyncpg.Pool, run_id: str, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT id, chat_id, status, route, guard, degraded, usage, cost_usd, error_code,
               created_at, updated_at
        FROM runs WHERE id = $1 AND user_id = $2
        """,
        run_id,
        user_id,
    )


async def list_steps(pool: asyncpg.Pool, run_id: str) -> list[asyncpg.Record]:
    return await pool.fetch(
        """
        SELECT id, parent_step_id, seq, kind, name, output_summary, status, duration_ms,
               tokens_in, tokens_out, cost_usd
        FROM run_steps WHERE run_id = $1 ORDER BY seq
        """,
        run_id,
    )


async def fail_stale_runs(pool: asyncpg.Pool, user_id: str) -> int:
    """Runs orphaned by a crashed/absent worker would block the chat forever (ADR-28)."""
    result = await pool.execute(
        f"""
        UPDATE runs SET status = 'FAILED', error_code = 'WORKER_LOST', updated_at = now()
        WHERE user_id = $1 AND status IN {ACTIVE} AND (
            (status = 'RUNNING' AND coalesce(heartbeat_at, updated_at)
                < now() - make_interval(secs => $2))
            OR (status = 'QUEUED' AND created_at < now() - make_interval(secs => $3))
        )
        """,  # noqa: S608 - constant fragment, values are bound
        user_id,
        RUNNING_STALE_S,
        QUEUED_STALE_S,
    )
    return int(result.split()[-1])


async def fail_all_stale_runs(pool: asyncpg.Pool) -> int:
    """Admin action: same rule as fail_stale_runs, across every user."""
    result = await pool.execute(
        f"""
        UPDATE runs SET status = 'FAILED', error_code = 'WORKER_LOST', finished_at = now(),
                        updated_at = now()
        WHERE status IN {ACTIVE} AND (
            (status = 'RUNNING' AND coalesce(heartbeat_at, updated_at)
                < now() - make_interval(secs => $1))
            OR (status = 'QUEUED' AND created_at < now() - make_interval(secs => $2))
        )
        """,  # noqa: S608 - constant fragment, values are bound
        RUNNING_STALE_S,
        QUEUED_STALE_S,
    )
    return int(result.split()[-1])


async def count_active_for_user(pool: asyncpg.Pool, user_id: str) -> int:
    return int(
        await pool.fetchval(
            f"SELECT count(*) FROM runs WHERE user_id = $1 AND status IN {ACTIVE}",  # noqa: S608
            user_id,
        )
    )


async def has_active_run(pool: asyncpg.Pool, chat_id: str) -> bool:
    return bool(
        await pool.fetchval(
            f"SELECT EXISTS (SELECT 1 FROM runs WHERE chat_id = $1 AND status IN {ACTIVE})",  # noqa: S608
            chat_id,
        )
    )


async def mark_failed(pool: asyncpg.Pool, run_id: str, error_code: str) -> None:
    await pool.execute(
        "UPDATE runs SET status = 'FAILED', error_code = $2, updated_at = now() WHERE id = $1",
        run_id,
        error_code,
    )
