"""Per-user LLM usage from usage_ledger (written by the agent worker)."""

from dataclasses import dataclass
from datetime import date

import asyncpg

DAILY_WINDOW_DAYS = 7


@dataclass(frozen=True)
class DailyUsage:
    day: date
    cost_usd: float
    tokens: int


@dataclass(frozen=True)
class UsageTotals:
    cost_usd: float
    tokens_in: int
    tokens_out: int
    runs: int


async def totals(pool: asyncpg.Pool, user_id: str) -> UsageTotals:
    row = await pool.fetchrow(
        """
        SELECT coalesce(sum(cost_usd), 0) AS cost, coalesce(sum(tokens_in), 0) AS tin,
               coalesce(sum(tokens_out), 0) AS tout, count(DISTINCT run_id) AS runs
        FROM usage_ledger WHERE user_id = $1
        """,
        user_id,
    )
    return UsageTotals(float(row["cost"]), int(row["tin"]), int(row["tout"]), int(row["runs"]))


async def total_cost(pool: asyncpg.Pool, user_id: str) -> float:
    cost = await pool.fetchval(
        "SELECT coalesce(sum(cost_usd), 0) FROM usage_ledger WHERE user_id = $1", user_id
    )
    return float(cost)


async def daily(pool: asyncpg.Pool, user_id: str) -> list[DailyUsage]:
    """Last DAILY_WINDOW_DAYS days including today; days without usage are zero."""
    rows = await pool.fetch(
        """
        SELECT d::date AS day, coalesce(sum(u.cost_usd), 0) AS cost,
               coalesce(sum(u.tokens_in + u.tokens_out), 0) AS tokens
        FROM generate_series(current_date - ($2::int - 1), current_date, interval '1 day') AS d
        LEFT JOIN usage_ledger u ON u.user_id = $1 AND u.day = d::date
        GROUP BY d ORDER BY d
        """,
        user_id,
        DAILY_WINDOW_DAYS,
    )
    return [DailyUsage(r["day"], float(r["cost"]), int(r["tokens"])) for r in rows]
