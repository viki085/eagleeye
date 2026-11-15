"""Last-activity tracking for the demo machine's idle stop (Phase 7 wake/sleep)."""

import asyncio

from app.activity import ACTIVITY_KEY, ActivityMiddleware, idle_seconds
from fake_redis import FakeRedis


async def _app(scope, receive, send) -> None:  # noqa: ANN001
    return None


def _scope(path: str) -> dict:
    return {"type": "http", "path": path, "app": None}


def test_requests_record_activity_but_health_checks_do_not() -> None:
    redis = FakeRedis()
    clock = iter([1000.0, 1001.0, 1040.0])
    mw = ActivityMiddleware(_app, lambda: redis, clock=lambda: next(clock), every_s=30)

    async def run() -> None:
        await mw(_scope("/v1/health/live"), None, None)  # monitoring: not activity
        assert ACTIVITY_KEY not in redis.data
        await mw(_scope("/v1/chats"), None, None)  # t=1000: recorded
        await mw(_scope("/v1/chats"), None, None)  # t=1001: throttled
        await mw(_scope("/v1/me"), None, None)  # t=1040: recorded again

    asyncio.run(run())
    assert float(redis.data[ACTIVITY_KEY]) == 1040.0


def test_activity_is_best_effort_when_redis_is_down() -> None:
    mw = ActivityMiddleware(_app, lambda: FakeRedis(fail=True), clock=lambda: 5.0, every_s=30)
    asyncio.run(mw(_scope("/v1/chats"), None, None))  # no exception reaches the request


def test_idle_seconds() -> None:
    redis = FakeRedis()
    assert asyncio.run(idle_seconds(redis, now=2000.0)) is None  # never used since start
    redis.data[ACTIVITY_KEY] = "1400"
    assert asyncio.run(idle_seconds(redis, now=2000.0)) == 600.0
