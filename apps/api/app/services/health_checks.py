import asyncio
import logging
import time
from dataclasses import dataclass

import asyncpg
import httpx
import redis.asyncio as aioredis

from eagleeye_core.config import get_settings

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_S = 3.0


@dataclass(frozen=True)
class ServiceHealth:
    name: str
    status: str  # "up" | "down"
    latency_ms: int | None = None
    detail: str | None = None


async def _check_redis() -> ServiceHealth:
    settings = get_settings()
    start = time.perf_counter()
    client = aioredis.from_url(settings.redis_url, socket_connect_timeout=CHECK_TIMEOUT_S)
    try:
        await client.ping()
        return ServiceHealth("redis", "up", _ms(start))
    except Exception as exc:
        logger.warning("redis health check failed: %s", exc)
        return ServiceHealth("redis", "down", detail=type(exc).__name__)
    finally:
        await client.aclose()


async def _check_qdrant() -> ServiceHealth:
    settings = get_settings()
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
            resp = await client.get(f"{settings.qdrant_url}/readyz")
            resp.raise_for_status()
        return ServiceHealth("qdrant", "up", _ms(start))
    except Exception as exc:
        logger.warning("qdrant health check failed: %s", exc)
        return ServiceHealth("qdrant", "down", detail=type(exc).__name__)


async def _check_object_store() -> ServiceHealth:
    settings = get_settings()
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=CHECK_TIMEOUT_S) as client:
            resp = await client.get(settings.s3_endpoint_url)
        if resp.status_code >= 500:
            raise RuntimeError(f"object store returned {resp.status_code}")
        # Any non-5xx response (403 AccessDenied on anonymous ListBuckets is normal)
        # proves the S3 endpoint is serving.
        return ServiceHealth("object-store", "up", _ms(start))
    except Exception as exc:
        logger.warning("object store health check failed: %s", exc)
        return ServiceHealth("object-store", "down", detail=type(exc).__name__)


async def _check_postgres() -> ServiceHealth:
    settings = get_settings()
    start = time.perf_counter()
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(settings.database_url, timeout=CHECK_TIMEOUT_S)
        await conn.fetchval("SELECT 1")
        return ServiceHealth("supabase-pg", "up", _ms(start))
    except Exception as exc:
        logger.warning("postgres health check failed: %s", exc)
        return ServiceHealth("supabase-pg", "down", detail=type(exc).__name__)
    finally:
        if conn is not None:
            await conn.close()


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


async def check_all() -> list[ServiceHealth]:
    return list(
        await asyncio.gather(
            _check_redis(), _check_qdrant(), _check_object_store(), _check_postgres()
        )
    )
