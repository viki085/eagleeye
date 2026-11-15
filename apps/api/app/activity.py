"""When was EagleEye last used? (Phase 7 wake/sleep.)

Every API request except health checks records the time in Redis (at most once per
`every_s` per process, so it costs nothing). The demo machine's timer reads it through
scripts/idle_check.py and stops the machine after 30 idle minutes.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

ACTIVITY_KEY = "activity:last"
NOT_ACTIVITY = ("/v1/health", "/health")  # monitoring and load-balancer probes


class ActivityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        redis: Callable[[], Any],
        clock: Callable[[], float] = time.time,
        every_s: float = 30.0,
    ) -> None:
        self.app = app
        self._redis = redis
        self._clock = clock
        self._every = every_s
        self._last = 0.0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not str(scope.get("path", "")).startswith(NOT_ACTIVITY):
            now = self._clock()
            if now - self._last >= self._every:
                self._last = now
                try:
                    redis = self._redis()
                    if redis is not None:
                        await redis.set(ACTIVITY_KEY, str(now))
                except Exception:  # noqa: BLE001 - activity is best effort
                    logger.debug("could not record activity", exc_info=True)
        await self.app(scope, receive, send)


async def idle_seconds(redis: Any, now: float | None = None) -> float | None:
    """Seconds since the last recorded activity; None if nothing was recorded."""
    raw = await redis.get(ACTIVITY_KEY)
    if raw is None:
        return None
    return max((now if now is not None else time.time()) - float(raw), 0.0)
