import json
import logging
import time
from collections.abc import AsyncIterator
from uuid import UUID

from eagleeye_core.envelope import ok
from eagleeye_events import CANCEL_TTL_S, TERMINAL_EVENTS, cancel_key, read_events
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.auth import CurrentUser
from app.errors import ApiException
from app.repos import runs as runs_repo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/runs", tags=["runs"])

STREAM_MAX_LIFETIME_S = 600  # hard cap per SSE connection; client reconnects with Last-Event-ID
ACTIVE_STATUSES = {"QUEUED", "RUNNING"}


async def _owned(request: Request, run_id: UUID, user_id: str) -> dict:
    run = await runs_repo.get_owned_run(request.app.state.pool, str(run_id), user_id)
    if run is None:
        raise ApiException(404, "NOT_FOUND", "Run not found.")
    return dict(run)


@router.get("/{run_id}")
async def get_run(run_id: UUID, request: Request, user: CurrentUser) -> dict:
    run = await _owned(request, run_id, user.id)
    steps = await runs_repo.list_steps(request.app.state.pool, str(run_id))
    return ok({**run, "steps": [dict(s) for s in steps]})


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: UUID, request: Request, user: CurrentUser) -> dict:
    """Sets a flag the agent worker polls at safe points; the run ends as CANCELLED."""
    run = await _owned(request, run_id, user.id)
    if run["status"] not in ACTIVE_STATUSES:
        return ok({"run_id": str(run_id), "status": run["status"], "cancelled": False})
    await request.app.state.redis.set(cancel_key(str(run_id)), "1", ex=CANCEL_TTL_S)
    return ok({"run_id": str(run_id), "status": run["status"], "cancelled": True})


@router.get("/{run_id}/stream")
async def stream_run(run_id: UUID, request: Request, user: CurrentUser) -> StreamingResponse:
    await _owned(request, run_id, user.id)
    last_event_id = request.headers.get("Last-Event-ID", "0")
    redis = request.app.state.redis
    rid = str(run_id)

    async def generate() -> AsyncIterator[str]:
        last_id = last_event_id
        deadline = time.monotonic() + STREAM_MAX_LIFETIME_S
        while time.monotonic() < deadline:
            if await request.is_disconnected():
                return
            events, last_id = await read_events(redis, rid, last_id)
            if not events:
                yield ": heartbeat\n\n"
                continue
            for stream_id, seq, event, data in events:
                payload = json.dumps({"seq": seq, **data})
                yield f"id: {stream_id}\nevent: {event}\ndata: {payload}\n\n"
                if event in TERMINAL_EVENTS:
                    return
        logger.warning("stream for run %s hit lifetime cap", rid)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
