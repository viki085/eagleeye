"""EagleEye's own cache: reuses results of repeatable LLM steps and whole answers (ADR-21).

Entries live in Redis with a TTL. Keys are a SHA-256 of everything the result depends on, so a
hit is only possible when the inputs are identical. Every lookup is counted per hour (lookups,
hits, estimated USD saved) for the admin console. The cache fails open: if Redis errors, a
lookup is a miss and a write is skipped; answering never depends on the cache.
"""

import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

PREFIX = "appcache"
STATS_TTL_S = 45 * 24 * 3600  # long enough for the console's 30-day range
KINDS = ("guard", "rewrite", "embedding", "answer")


def cache_key(kind: str, parts: Sequence[Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(list(parts), sort_keys=True, default=str).encode()
    ).hexdigest()
    return f"{PREFIX}:{kind}:{digest}"


def stats_key(hour: datetime) -> str:
    return f"{PREFIX}:stats:{hour.astimezone(UTC):%Y%m%d%H}"


class AppCache:
    def __init__(self, redis: Any, ttl_s: int = 86400, enabled: bool = True) -> None:
        self._redis = redis
        self._ttl = ttl_s
        self.enabled = enabled and redis is not None

    async def get(self, kind: str, parts: Sequence[Any]) -> dict | None:
        """The cached value, or None. Counts the lookup (and the hit) for the console."""
        if not self.enabled:
            return None
        try:
            raw = await self._redis.get(cache_key(kind, parts))
            value = json.loads(raw) if raw else None
        except Exception:
            logger.warning("app cache read failed (%s); treating as a miss", kind, exc_info=True)
            return None
        saved = float(value.get("cost_usd", 0.0)) if isinstance(value, dict) else 0.0
        await self._count(kind, hit=value is not None, saved_usd=saved)
        return value if isinstance(value, dict) else None

    async def put(self, kind: str, parts: Sequence[Any], value: dict) -> None:
        if not self.enabled:
            return
        try:
            await self._redis.set(cache_key(kind, parts), json.dumps(value), ex=self._ttl)
        except Exception:
            logger.warning("app cache write failed (%s); skipped", kind, exc_info=True)

    async def _count(self, kind: str, hit: bool, saved_usd: float) -> None:
        key = stats_key(datetime.now(UTC))
        try:
            pipe = self._redis.pipeline()
            pipe.hincrby(key, f"{kind}:lookups", 1)
            if hit:
                pipe.hincrby(key, f"{kind}:hits", 1)
                if saved_usd > 0:
                    pipe.hincrbyfloat(key, f"{kind}:saved_usd", saved_usd)
            pipe.expire(key, STATS_TTL_S)
            await pipe.execute()
        except Exception:
            logger.debug("app cache stats write failed", exc_info=True)


def _empty() -> dict[str, Any]:
    return {k: {"lookups": 0, "hits": 0, "saved_usd": 0.0} for k in KINDS}


def _add(total: dict[str, Any], fields: dict) -> None:
    for raw_field, raw_value in fields.items():
        name = raw_field.decode() if isinstance(raw_field, bytes) else str(raw_field)
        kind, _, metric = name.partition(":")
        if kind not in total or metric not in total[kind]:
            continue
        value = raw_value.decode() if isinstance(raw_value, bytes) else raw_value
        total[kind][metric] += float(value) if metric == "saved_usd" else int(float(value))


def summarise(by_kind: dict[str, Any]) -> dict[str, Any]:
    lookups = sum(v["lookups"] for v in by_kind.values())
    hits = sum(v["hits"] for v in by_kind.values())
    return {
        "lookups": lookups,
        "hits": hits,
        "hit_rate": round(hits / lookups, 4) if lookups else None,
        "saved_usd": round(sum(v["saved_usd"] for v in by_kind.values()), 6),
        "by_kind": {k: {**v, "saved_usd": round(v["saved_usd"], 6)} for k, v in by_kind.items()},
    }


async def read_stats(redis: Any, start: datetime, end: datetime) -> dict[datetime, dict[str, Any]]:
    """Hourly counters between start and end (UTC), keyed by the hour. Empty hours omitted."""
    hours: list[datetime] = []
    hour = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    while hour <= end:
        hours.append(hour)
        hour += timedelta(hours=1)
    pipe = redis.pipeline()
    for h in hours:
        pipe.hgetall(stats_key(h))
    rows = await pipe.execute()
    out: dict[datetime, dict[str, Any]] = {}
    for h, fields in zip(hours, rows, strict=True):
        if fields:
            totals = _empty()
            _add(totals, fields)
            out[h] = totals
    return out


def bucket_stats(
    hourly: dict[datetime, dict[str, Any]], buckets: Sequence[datetime], step: timedelta
) -> list[dict[str, Any]]:
    """Folds hourly counters into the console's buckets ([bucket, bucket + step))."""
    out = []
    for b in buckets:
        totals = _empty()
        for hour, stats in hourly.items():
            if b <= hour < b + step:
                for kind in KINDS:
                    for metric in ("lookups", "hits", "saved_usd"):
                        totals[kind][metric] += stats[kind][metric]
        s = summarise(totals)
        out.append({"lookups": s["lookups"], "hits": s["hits"], "hit_rate": s["hit_rate"]})
    return out


def total_stats(hourly: dict[datetime, dict[str, Any]]) -> dict[str, Any]:
    totals = _empty()
    for stats in hourly.values():
        for kind in KINDS:
            for metric in ("lookups", "hits", "saved_usd"):
                totals[kind][metric] += stats[kind][metric]
    return summarise(totals)
