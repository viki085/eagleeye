"""Organisation settings stored in app_settings; the environment supplies the defaults."""

import json

import asyncpg

MONTHLY_BUDGET = "monthly_budget_usd"
MAX_MONTHLY_BUDGET_USD = 1_000_000.0


async def monthly_budget(pool: asyncpg.Pool, default: float) -> float:
    raw = await pool.fetchval("SELECT value FROM app_settings WHERE key = $1", MONTHLY_BUDGET)
    if raw is None:
        return float(default)
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return float(value)
    except (TypeError, ValueError):
        return float(default)


async def set_monthly_budget(pool: asyncpg.Pool, value: float, user_id: str) -> None:
    await pool.execute(
        """
        INSERT INTO app_settings (key, value, updated_by, updated_at)
        VALUES ($1, $2::jsonb, $3, now())
        ON CONFLICT (key) DO UPDATE
           SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by, updated_at = now()
        """,
        MONTHLY_BUDGET,
        json.dumps(round(value, 2)),
        user_id,
    )
