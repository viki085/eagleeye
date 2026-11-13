"""Every statement — executed or rejected — lands in sql_query_log (C5 §5)."""

import hashlib
import logging

import asyncpg

logger = logging.getLogger(__name__)
MAX_SQL_CHARS = 8000


async def log_query(
    pool: asyncpg.Pool,
    *,
    run_id: str | None,
    user_id: str | None,
    source_id: str | None,
    sql: str,
    validated: bool,
    rows: int | None = None,
    duration_ms: int | None = None,
    rejected_reason: str | None = None,
) -> None:
    try:
        await pool.execute(
            """
            INSERT INTO sql_query_log (run_id, user_id, data_source_id, sql_hash, sql_text, rows,
                                       duration_ms, validated, rejected_reason, origin)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'gateway')
            """,
            run_id,
            user_id,
            source_id,
            hashlib.sha256(sql.encode()).hexdigest(),
            sql[:MAX_SQL_CHARS],
            rows,
            duration_ms,
            validated,
            rejected_reason[:500] if rejected_reason else None,
        )
    except Exception:  # auditing must never take the gateway down; it must be noticed
        logger.exception("failed to write sql_query_log")
