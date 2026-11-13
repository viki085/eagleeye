"""Fixed-window rate limits in Redis (C2/C8: every endpoint is limited).

Keyed by the VERIFIED user id (or client IP before authentication), never by anything the
client could forge. Fails open: if Redis errors, the request goes through and is logged —
the limiter must not take the app down.
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

from app.errors import ApiException

logger = logging.getLogger(__name__)

STREAM_SLOT_TTL_S = 900  # safety expiry: a crashed process can't hold stream slots forever


@dataclass(frozen=True)
class Limit:
    name: str
    per_minute: int


async def hit(redis: Any, limit: Limit, subject: str, now: float | None = None) -> None:
    """Counts one request; raises 429 with Retry-After when the window is full."""
    now = time.time() if now is None else now
    window = int(now // 60)
    key = f"rl:{limit.name}:{subject}:{window}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 120)
    except Exception:
        logger.warning(
            "rate limiter unavailable; allowing %s for %s", limit.name, subject, exc_info=True
        )
        return
    if count > limit.per_minute:
        retry_after = max(1, 60 - int(now % 60))
        raise ApiException(
            429,
            "RATE_LIMITED",
            "Too many requests. Please wait a moment and try again.",
            headers={"Retry-After": str(retry_after)},
        )


class StreamSlots:
    """At most N open answer streams per user; the caller MUST release in `finally`."""

    def __init__(self, redis: Any, user_id: str, max_streams: int) -> None:
        self._redis = redis
        self._key = f"streams:{user_id}"
        self._max = max_streams
        self._held = False

    async def acquire(self) -> None:
        try:
            count = await self._redis.incr(self._key)
            await self._redis.expire(self._key, STREAM_SLOT_TTL_S)
        except Exception:
            logger.warning("stream slot counter unavailable; allowing stream", exc_info=True)
            return
        self._held = True
        if count > self._max:
            await self.release()
            raise ApiException(
                429,
                "RATE_LIMITED",
                "Too many open answers in other tabs. Close one and try again.",
                headers={"Retry-After": "5"},
            )

    async def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            if await self._redis.decr(self._key) <= 0:
                await self._redis.delete(self._key)
        except Exception:
            logger.warning("could not release stream slot %s", self._key, exc_info=True)
