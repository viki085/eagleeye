"""Admin console API. Every route requires the admin role, re-read from the database.

Views are not audited (the console refreshes often); actions are, in security_events.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from eagleeye_core.queues import AGENT_QUEUE, INGEST_QUEUE
from eagleeye_core.switches import DESCRIPTIONS, SWITCHES, Switch, killed_switches, switch_key
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel

from app.repos import admin_metrics as metrics
from app.repos import admin_overview
from app.repos import runs as runs_repo
from app.services.health_checks import check_all, check_databases
from app.services.permissions import AdminUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

OVERVIEW_CACHE_S = 60

RangeParam = Annotated[Literal["24h", "7d", "30d"], Query()]
SortParam = Annotated[Literal["last_seen", "cost", "runs", "email"], Query()]


class SwitchBody(BaseModel):
    killed: bool


def _window(range_: str) -> metrics.Window:
    return metrics.WINDOWS[range_]


async def _cached_overview(request: Request, range_: str) -> dict[str, Any]:
    """Aggregates cached per range for OVERVIEW_CACHE_S: many admins refreshing cost one set of
    queries a minute on the shared database. Redis errors fall back to a direct query."""
    redis, key = request.app.state.redis, f"admin:overview:{range_}"
    try:
        hit = await redis.get(key)
        if hit:
            return json.loads(hit)
    except Exception:
        logger.warning("overview cache read failed", exc_info=True)
    data = {
        **await admin_overview.overview(request.app.state.pool, _window(range_)),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    try:
        await redis.set(key, json.dumps(data), ex=OVERVIEW_CACHE_S)
    except Exception:
        logger.warning("overview cache write failed", exc_info=True)
    return data


async def _live(request: Request) -> dict[str, Any]:
    """Cheap, current-state signals: two database pings and one indexed count. No call reaches
    the agent workers or the data gateway, so the answer path is untouched."""
    pool = request.app.state.pool
    databases = await check_databases()
    runs = await metrics.run_counts(pool, runs_repo.RUNNING_STALE_S, runs_repo.QUEUED_STALE_S)
    return {"databases": admin_overview.database_health(databases), "agents": runs}


@router.get("/overview")
async def overview(
    request: Request,
    _admin: AdminUser,
    range: RangeParam = "7d",  # noqa: A002
) -> dict:
    return ok(
        {"range": range, **await _cached_overview(request, range), "live": await _live(request)}
    )


@router.get("/users")
async def users(
    request: Request,
    _admin: AdminUser,
    range: RangeParam = "7d",  # noqa: A002
    sort: SortParam = "last_seen",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=metrics.MAX_PAGE)] = 50,
) -> dict:
    data = await metrics.users(
        request.app.state.pool,
        _window(range),
        sort,
        offset,
        limit,
        get_settings().usage_limit_usd,
    )
    return ok({"range": range, "usage_limit_usd": get_settings().usage_limit_usd, **data})


@router.get("/usage")
async def usage(
    request: Request,
    _admin: AdminUser,
    range: RangeParam = "7d",  # noqa: A002
) -> dict:
    return ok({"range": range, **await metrics.usage(request.app.state.pool, _window(range))})


@router.get("/safety")
async def safety(
    request: Request,
    _admin: AdminUser,
    range: RangeParam = "7d",  # noqa: A002
) -> dict:
    return ok({"range": range, **await metrics.safety(request.app.state.pool, _window(range))})


@router.get("/content")
async def content(request: Request, _admin: AdminUser) -> dict:
    return ok(await metrics.content(request.app.state.pool))


async def _queue_depths(request: Request) -> dict[str, int | None]:
    redis = request.app.state.redis
    depths: dict[str, int | None] = {}
    for queue in (AGENT_QUEUE, INGEST_QUEUE):
        try:
            depths[queue] = int(await redis.llen(queue))
        except Exception:
            logger.warning("could not read queue depth for %s", queue, exc_info=True)
            depths[queue] = None
    return depths


@router.get("/system")
async def system(request: Request, _admin: AdminUser) -> dict:
    state = request.app.state
    services = [s.__dict__ for s in await check_all()]
    switches = await killed_switches(state.redis)
    return ok(
        {
            "services": services,
            "queues": await _queue_depths(request),
            "runs": await metrics.run_counts(
                state.pool, runs_repo.RUNNING_STALE_S, runs_repo.QUEUED_STALE_S
            ),
            "switches": [
                {"name": s, "killed": switches[s], "description": DESCRIPTIONS[s]} for s in SWITCHES
            ],
        }
    )


@router.post("/switches/{name}")
async def set_switch(name: Switch, body: SwitchBody, request: Request, admin: AdminUser) -> dict:
    redis = request.app.state.redis
    # audit first: if the audit write fails, the switch must not change unrecorded
    await metrics.record_admin_action(
        request.app.state.pool,
        admin.id,
        "switch_off" if body.killed else "switch_on",
        {"switch": name},
    )
    if body.killed:
        await redis.set(switch_key(name), admin.id)
    else:
        await redis.delete(switch_key(name))
    logger.warning("admin %s turned %s %s", admin.email, name, "OFF" if body.killed else "ON")
    return ok({"name": name, "killed": body.killed})


@router.post("/runs/clear-stuck")
async def clear_stuck(request: Request, admin: AdminUser) -> dict:
    cleared = await runs_repo.fail_all_stale_runs(request.app.state.pool)
    await metrics.record_admin_action(
        request.app.state.pool, admin.id, "clear_stuck_runs", {"cleared": cleared}
    )
    return ok({"cleared": cleared})
