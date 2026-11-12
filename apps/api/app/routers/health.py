import asyncio

from eagleeye_core.envelope import ok
from fastapi import APIRouter

from app.services.health_checks import ServiceHealth, check_all

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness + dependency readiness: reports each infra service's status."""
    results: list[ServiceHealth] = await check_all()
    overall = all(s.status == "up" for s in results)
    return ok({"overall": "up" if overall else "degraded", "services": [s.__dict__ for s in results]})


@router.get("/health/live")
async def live() -> dict:
    """Plain liveness for container orchestrators; no dependency fan-out."""
    await asyncio.sleep(0)
    return ok({"status": "up"})
