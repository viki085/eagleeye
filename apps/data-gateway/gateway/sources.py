"""Connection pools + concurrency limits per data source (credentials stay in this process)."""

import asyncio
import os

import asyncpg
from eagleeye_catalog.models import SourceInfo
from eagleeye_core.config import get_settings


def resolve_dsn(dsn_env: str) -> str:
    value = getattr(get_settings(), dsn_env.lower(), None) or os.environ.get(dsn_env)
    if not value:
        raise RuntimeError(f"{dsn_env} is not configured")
    return str(value)


class SourcePools:
    def __init__(self, max_concurrency: int) -> None:
        self._max = max_concurrency
        self._pools: dict[str, asyncpg.Pool] = {}
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    async def pool_for(self, source: SourceInfo) -> asyncpg.Pool:
        async with self._lock:
            pool = self._pools.get(source.id)
            if pool is None:
                pool = await asyncpg.create_pool(
                    resolve_dsn(source.dsn_env),
                    min_size=1,
                    max_size=self._max,
                    server_settings={"application_name": "eagleeye-data-gateway"},
                    command_timeout=source.timeout_s + 5,
                )
                self._pools[source.id] = pool
            return pool

    def semaphore_for(self, source_id: str) -> asyncio.Semaphore:
        sem = self._sems.get(source_id)
        if sem is None:
            sem = self._sems[source_id] = asyncio.Semaphore(self._max)
        return sem

    async def close(self) -> None:
        for pool in self._pools.values():
            await pool.close()
