import asyncpg


async def create_run(conn: asyncpg.Connection, chat_id: str, user_id: str) -> str:
    return str(
        await conn.fetchval(
            "INSERT INTO runs (chat_id, user_id, status) VALUES ($1, $2, 'QUEUED') RETURNING id",
            chat_id,
            user_id,
        )
    )


async def get_owned_run(pool: asyncpg.Pool, run_id: str, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        "SELECT * FROM runs WHERE id = $1 AND user_id = $2", run_id, user_id
    )


async def mark_running(pool: asyncpg.Pool, run_id: str, model_ids: dict) -> None:
    await pool.execute(
        "UPDATE runs SET status = 'RUNNING', model_ids = $2, updated_at = now() WHERE id = $1",
        run_id,
        model_ids,
    )


async def mark_finished(
    pool: asyncpg.Pool,
    run_id: str,
    status: str,
    usage: dict | None = None,
    cost_usd: float | None = None,
    error_code: str | None = None,
) -> None:
    await pool.execute(
        """
        UPDATE runs SET status = $2, usage = $3, cost_usd = $4, error_code = $5,
                        updated_at = now()
        WHERE id = $1
        """,
        run_id,
        status,
        usage,
        cost_usd,
        error_code,
    )
