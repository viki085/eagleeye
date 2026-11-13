"""The gateway's decision flow for one request. Never trusts the caller beyond the token."""

import logging
from dataclasses import dataclass, replace
from typing import Any

import asyncpg
from eagleeye_catalog.service import CatalogService
from eagleeye_core.service_auth import ContextToken
from eagleeye_core.storage import ObjectStore
from eagleeye_sqlsafe.errors import SqlRejected
from eagleeye_sqlsafe.validator import validate

from gateway import audit
from gateway.artifacts import save_artifact
from gateway.executor import PREVIEW_ROWS, QueryTooExpensive, jsonable, run_query
from gateway.sources import SourcePools

logger = logging.getLogger(__name__)


class GatewayError(Exception):
    """Plain class (not a frozen dataclass): asyncio/contextlib reassign __traceback__."""

    def __init__(self, status: int, code: str, user_safe_error: str, retryable: bool = False):
        super().__init__(f"{code}: {user_safe_error}")
        self.status = status
        self.code = code
        self.user_safe_error = user_safe_error
        self.retryable = retryable


@dataclass(frozen=True)
class GatewayDeps:
    meta_pool: asyncpg.Pool
    catalog: CatalogService
    sources: SourcePools
    store: ObjectStore
    explain_max_rows: int


async def user_role(pool: asyncpg.Pool, user_id: str) -> str | None:
    row = await pool.fetchrow("SELECT role, status FROM users WHERE id = $1", user_id)
    if row is None or row["status"] != "active":
        return None
    return str(row["role"])


async def execute(deps: GatewayDeps, token: ContextToken, sql: str, title: str) -> dict[str, Any]:
    role = await user_role(deps.meta_pool, token.user_id)  # from the DB, never the caller
    if role is None:
        raise GatewayError(403, "FORBIDDEN", "User is not active.")
    acc = await deps.catalog.access(token.source_id, role)
    if acc is None:
        raise GatewayError(403, "NO_ACCESS", "You don't have access to this data source.")
    max_rows = acc.source.max_rows
    policy = replace(acc.policy, default_limit=max_rows + 1, max_limit=max_rows + 1)
    log = {"run_id": token.run_id, "user_id": token.user_id, "source_id": acc.source.id}
    try:
        validated = validate(sql, policy)  # the control; the worker's check is a convenience
    except SqlRejected as exc:
        await audit.log_query(
            deps.meta_pool, sql=sql, validated=False, rejected_reason=exc.code, **log
        )
        raise GatewayError(422, exc.code, exc.user_message, retryable=True) from exc
    result = await _run(deps, acc.source, validated.sql, max_rows, log)
    artifact_id = await save_artifact(
        deps.store,
        deps.meta_pool,
        user_id=token.user_id,
        run_id=token.run_id,
        title=title,
        result=result,
        sql=validated.sql,
        source_id=acc.source.id,
    )
    await audit.log_query(
        deps.meta_pool,
        sql=validated.sql,
        validated=True,
        rows=len(result.rows),
        duration_ms=result.duration_ms,
        **log,
    )
    return {
        "ok": True,
        "artifact_id": artifact_id,
        "sql": validated.sql,
        "columns": [{"name": n, "type": t} for n, t in result.columns],
        "row_count": len(result.rows),
        "truncated": result.truncated,
        "preview": [[jsonable(v) for v in row] for row in result.rows[:PREVIEW_ROWS]],
        "duration_ms": result.duration_ms,
    }


async def _run(deps: GatewayDeps, source: Any, sql: str, max_rows: int, log: dict) -> Any:
    pool = await deps.sources.pool_for(source)
    async with deps.sources.semaphore_for(source.id):
        try:
            return await run_query(pool, sql, source.timeout_s, max_rows, deps.explain_max_rows)
        except QueryTooExpensive as exc:
            await audit.log_query(
                deps.meta_pool, sql=sql, validated=False, rejected_reason="TOO_EXPENSIVE", **log
            )
            raise GatewayError(
                422,
                "TOO_EXPENSIVE",
                f"The query would scan too many rows (~{exc.estimated_rows:,}). "
                "Aggregate or filter.",
                retryable=True,
            ) from exc
        except asyncpg.QueryCanceledError as exc:
            await audit.log_query(
                deps.meta_pool, sql=sql, validated=True, rejected_reason="TIMEOUT", **log
            )
            raise GatewayError(
                422, "TIMEOUT", f"The query took longer than {source.timeout_s}s.", retryable=True
            ) from exc
        except asyncpg.PostgresError as exc:
            # Postgres messages ("column x does not exist") are what the agent needs to
            # self-correct; driver/connection details never leave the gateway.
            await audit.log_query(
                deps.meta_pool,
                sql=sql,
                validated=True,
                rejected_reason=f"DB_ERROR {exc.sqlstate}",
                **log,
            )
            raise GatewayError(
                422, "DB_ERROR", str(getattr(exc, "message", exc))[:300], retryable=True
            ) from exc
        except (TimeoutError, OSError, asyncpg.InterfaceError) as exc:
            logger.exception("source %s unavailable", source.name)
            raise GatewayError(
                503, "SOURCE_UNAVAILABLE", "The data source is unavailable."
            ) from exc
