"""Work still in flight, as one JSON line (used by stop-eagleeye.ps1 to shut down safely).

  uv run --package eagleeye-api python scripts/drain_status.py

{"runs": answers queued/running, "agent_queue": tasks waiting, "ingest_queue": tasks waiting,
 "documents": uploads being processed, "datasets": data files being profiled, "error": null}
Exits 0 even when a backend is down (reported in "error"), so the caller can decide.
"""

import asyncio
import json

import asyncpg
import redis.asyncio as aioredis
from eagleeye_core.config import get_settings
from eagleeye_core.queues import AGENT_QUEUE, INGEST_QUEUE


async def main() -> dict:
    s = get_settings()
    out: dict = {"runs": 0, "agent_queue": 0, "ingest_queue": 0, "documents": 0, "datasets": 0,
                 "error": None}
    errors = []
    try:
        conn = await asyncpg.connect(s.database_url, timeout=5)
        try:
            out["runs"] = await conn.fetchval(
                "SELECT count(*) FROM runs WHERE status IN ('QUEUED', 'RUNNING')"
            )
            out["documents"] = await conn.fetchval(
                "SELECT count(*) FROM documents WHERE status IN "
                "('UPLOADING', 'SCANNING', 'PARSING', 'CHUNKING', 'EMBEDDING')"
            )
            out["datasets"] = await conn.fetchval(
                "SELECT count(*) FROM datasets WHERE status IN ('UPLOADED', 'PROFILING')"
            )
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        errors.append(f"database: {type(exc).__name__}")
    try:
        r = aioredis.from_url(s.redis_url, socket_connect_timeout=5)
        try:
            out["agent_queue"] = int(await r.llen(AGENT_QUEUE))
            out["ingest_queue"] = int(await r.llen(INGEST_QUEUE))
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        errors.append(f"redis: {type(exc).__name__}")
    out["error"] = "; ".join(errors) or None
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
