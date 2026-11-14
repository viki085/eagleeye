from datetime import UTC, datetime, timedelta

from eagleeye_core.app_cache import (
    AppCache,
    bucket_stats,
    cache_key,
    read_stats,
    stats_key,
    total_stats,
)


class FakePipe:
    def __init__(self, redis: "FakeRedis") -> None:
        self.r, self.ops = redis, []

    def __getattr__(self, name):  # noqa: ANN001, ANN204 - queue any command
        return lambda *a: self.ops.append((name, a))

    async def execute(self) -> list:
        return [await getattr(self.r, name)(*a) for name, a in self.ops]


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, float]] = {}
        self.fail = fail

    async def get(self, key: str):  # noqa: ANN201
        if self.fail:
            raise ConnectionError("down")
        return self.kv.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail:
            raise ConnectionError("down")
        self.kv[key] = value

    def pipeline(self) -> FakePipe:
        return FakePipe(self)

    async def hincrby(self, key: str, field: str, n: int) -> None:
        h = self.hashes.setdefault(key, {})
        h[field] = h.get(field, 0) + n

    async def hincrbyfloat(self, key: str, field: str, n: float) -> None:
        await self.hincrby(key, field, n)  # type: ignore[arg-type]

    async def expire(self, key: str, ttl: int) -> None:
        return None

    async def hgetall(self, key: str) -> dict:
        return {k.encode(): str(v).encode() for k, v in self.hashes.get(key, {}).items()}


def test_key_depends_on_every_part_and_kind() -> None:
    assert cache_key("guard", ["a", 1]) == cache_key("guard", ["a", 1])
    assert cache_key("guard", ["a", 1]) != cache_key("guard", ["a", 2])
    assert cache_key("guard", ["a"]) != cache_key("rewrite", ["a"])


async def test_miss_then_hit_counts_lookups_hits_and_savings() -> None:
    r = FakeRedis()
    cache = AppCache(r)
    assert await cache.get("guard", ["q"]) is None
    await cache.put("guard", ["q"], {"raw": "{}", "cost_usd": 0.002})
    assert (await cache.get("guard", ["q"]))["raw"] == "{}"
    stats = total_stats(
        await read_stats(r, datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC))
    )
    assert stats["by_kind"]["guard"] == {"lookups": 2, "hits": 1, "saved_usd": 0.002}
    assert stats["hit_rate"] == 0.5 and stats["saved_usd"] == 0.002


async def test_redis_errors_never_break_answering() -> None:
    cache = AppCache(FakeRedis(fail=True))
    await cache.put("answer", ["q"], {"text": "x"})
    assert await cache.get("answer", ["q"]) is None


async def test_disabled_cache_does_nothing() -> None:
    r = FakeRedis()
    cache = AppCache(r, enabled=False)
    await cache.put("guard", ["q"], {"raw": "{}"})
    assert await cache.get("guard", ["q"]) is None and r.kv == {} and r.hashes == {}


async def test_hourly_counters_fold_into_console_buckets() -> None:
    r = FakeRedis()
    day = datetime(2026, 11, 13, tzinfo=UTC)
    r.hashes[stats_key(day + timedelta(hours=3))] = {"guard:lookups": 4, "guard:hits": 1}
    r.hashes[stats_key(day + timedelta(hours=20))] = {"answer:lookups": 2, "answer:hits": 2}
    r.hashes[stats_key(day + timedelta(days=1, hours=1))] = {"rewrite:lookups": 5}
    hourly = await read_stats(r, day, day + timedelta(days=2))
    days = bucket_stats(hourly, [day, day + timedelta(days=1)], timedelta(days=1))
    assert days[0] == {"lookups": 6, "hits": 3, "hit_rate": 0.5}
    assert days[1] == {"lookups": 5, "hits": 0, "hit_rate": 0.0}
