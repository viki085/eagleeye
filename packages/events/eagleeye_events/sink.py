"""Redis Stream event sink/reader. One writer per run stamps a gapless `seq` (LLD §2.3)."""

import json
from typing import Any

import redis.asyncio as aioredis

from eagleeye_events.names import RUN_DONE, RUN_ERROR

STREAM_TTL_S = 3600
TERMINAL_EVENTS = {RUN_DONE, RUN_ERROR}


CANCEL_TTL_S = 600


def stream_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def cancel_key(run_id: str) -> str:
    """Set by the API when the user presses Stop; polled by the agent worker."""
    return f"run:{run_id}:cancel"


class EventSink:
    def __init__(self, redis: aioredis.Redis, run_id: str) -> None:
        self._redis = redis
        self._key = stream_key(run_id)
        self._seq = 0

    async def emit(self, event: str, data: dict[str, Any]) -> None:
        payload = {"seq": self._seq, "event": event, "data": json.dumps(data, default=str)}
        await self._redis.xadd(self._key, payload)
        if self._seq == 0:
            await self._redis.expire(self._key, STREAM_TTL_S)
        self._seq += 1


async def read_events(
    redis: aioredis.Redis, run_id: str, last_stream_id: str = "0", block_ms: int = 15000
) -> tuple[list[tuple[str, int, str, dict[str, Any]]], str]:
    """Returns ([(stream_id, seq, event, data)], new_last_id). Empty list = heartbeat window."""
    try:
        resp = await redis.xread({stream_key(run_id): last_stream_id}, block=block_ms, count=100)
    except (TimeoutError, aioredis.ConnectionError):
        # Transient redis hiccup → emit a heartbeat window instead of killing the SSE stream.
        return [], last_stream_id
    if not resp:
        return [], last_stream_id
    events: list[tuple[str, int, str, dict[str, Any]]] = []
    new_last = last_stream_id
    for _key, entries in resp:
        for stream_id, fields in entries:
            sid = stream_id.decode() if isinstance(stream_id, bytes) else stream_id
            f = {
                (k.decode() if isinstance(k, bytes) else k): (
                    v.decode() if isinstance(v, bytes) else v
                )
                for k, v in fields.items()
            }
            events.append((sid, int(f["seq"]), f["event"], json.loads(f["data"])))
            new_last = sid
    return events, new_last
