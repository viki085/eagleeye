import json
import logging
import time
from collections.abc import AsyncIterator

from eagleeye_core.envelope import ok
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser
from app.events import TERMINAL_EVENTS, read_events
from app.repos import runs as runs_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])

STREAM_MAX_LIFETIME_S = 600  # hard cap per SSE connection; client reconnects with Last-Event-ID


@router.get("/{run_id}")
async def get_run(run_id: str, request: Request, user: CurrentUser) -> dict:
    run = await runs_repo.get_owned_run(request.app.state.pool, run_id, user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return ok(dict(run))


@router.get("/{run_id}/stream")
async def stream_run(run_id: str, request: Request, user: CurrentUser) -> StreamingResponse:
    run = await runs_repo.get_owned_run(request.app.state.pool, run_id, user.id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    last_event_id = request.headers.get("Last-Event-ID", "0")
    redis = request.app.state.redis

    async def generate() -> AsyncIterator[str]:
        last_id = last_event_id
        if run["status"] in ("SUCCEEDED", "FAILED", "CANCELLED") and last_id == "0":
            # Replay still works from Redis within TTL; after that, client refetches the chat.
            pass
        deadline = time.monotonic() + STREAM_MAX_LIFETIME_S
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            events, last_id = await read_events(redis, run_id, last_id)
            if not events:
                yield ": heartbeat\n\n"
                continue
            for stream_id, seq, event, data in events:
                payload = json.dumps({"seq": seq, **data})
                yield f"id: {stream_id}\nevent: {event}\ndata: {payload}\n\n"
                if event in TERMINAL_EVENTS:
                    return
        logger.warning("stream for run %s hit lifetime cap", run_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
