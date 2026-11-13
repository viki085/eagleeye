"""Run one validated SELECT in a READ ONLY transaction with a statement timeout."""

import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import asyncpg

PREVIEW_ROWS = 50
CURSOR_PREFETCH = 500


class QueryTooExpensive(Exception):  # noqa: N818
    def __init__(self, estimated_rows: int) -> None:
        super().__init__(f"estimated {estimated_rows} rows")
        self.estimated_rows = estimated_rows


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[tuple[str, str], ...]  # (name, postgres type)
    rows: list[tuple[Any, ...]]
    truncated: bool
    duration_ms: int


def unique_names(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for name in names:
        n = seen.get(name, 0)
        seen[name] = n + 1
        out.append(name if n == 0 else f"{name}_{n + 1}")
    return out


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return "<binary>"
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return json.loads(json.dumps(value, default=str))
    return str(value)


def _max_plan_rows(node: dict) -> int:
    rows = int(node.get("Plan Rows", 0))
    for child in node.get("Plans", []) or []:
        rows = max(rows, _max_plan_rows(child))
    return rows


async def explain_check(conn: asyncpg.Connection, sql: str, max_rows: int) -> None:
    raw = await conn.fetchval(f"EXPLAIN (FORMAT JSON) {sql}")  # sql already validated by sqlsafe
    plan = json.loads(raw) if isinstance(raw, str) else raw
    estimated = _max_plan_rows(plan[0]["Plan"])
    if estimated > max_rows:
        raise QueryTooExpensive(estimated)


async def run_query(
    pool: asyncpg.Pool, sql: str, timeout_s: int, max_rows: int, explain_max_rows: int
) -> QueryResult:
    started = time.monotonic()
    async with pool.acquire() as conn, conn.transaction(readonly=True):
        await conn.execute(f"SET LOCAL statement_timeout = '{int(timeout_s)}s'")
        await explain_check(conn, sql, explain_max_rows)
        stmt = await conn.prepare(sql)
        attrs = stmt.get_attributes()
        rows: list[tuple[Any, ...]] = []
        async for record in stmt.cursor(prefetch=CURSOR_PREFETCH):
            rows.append(tuple(record.values()))
            if len(rows) > max_rows:
                break
    truncated = len(rows) > max_rows
    names = unique_names([a.name for a in attrs])
    return QueryResult(
        columns=tuple(zip(names, (a.type.name for a in attrs), strict=True)),
        rows=rows[:max_rows],
        truncated=truncated,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
