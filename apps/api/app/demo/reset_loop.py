"""Resets the demo account about every DEMO_RESET_HOURS, but only while nobody is using it.

Runs inside each API process; a Redis key both spaces resets out and acts as the lock, so
several API processes (cloud scale mode) still reset once per period.
"""

import asyncio
import logging
from typing import Any

from eagleeye_core.config import Settings

from app.demo import account

logger = logging.getLogger(__name__)

CHECK_EVERY_S = 15 * 60
IDLE_MINUTES = 30  # a visitor active in the last 30 minutes keeps their session
DONE_KEY = "demo:reset:done"  # exists until the next reset is due


async def demo_is_idle(pool: Any) -> bool:
    return bool(
        await pool.fetchval(
            "SELECT NOT EXISTS (SELECT 1 FROM users WHERE is_demo AND status = 'active' "
            "AND last_seen_at > now() - make_interval(mins => $1))",
            IDLE_MINUTES,
        )
    )


async def maybe_reset(state: Any, settings: Settings) -> bool:
    """One check: True when this call reset the account."""
    if settings.demo_reset_hours <= 0 or await account.demo_user_id(state.pool) is None:
        return False
    if await state.redis.exists(DONE_KEY) or not await demo_is_idle(state.pool):
        return False
    period = int(settings.demo_reset_hours * 3600)
    if not await state.redis.set(DONE_KEY, 1, ex=period, nx=True):
        return False  # another process took this period's reset
    await account.reset(state.pool, state.store, state.task_queue, state.clerk_admin, settings)
    return True


async def run_forever(state: Any, settings: Settings) -> None:
    while True:
        try:
            await maybe_reset(state, settings)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("demo reset check failed")
        await asyncio.sleep(CHECK_EVERY_S)
