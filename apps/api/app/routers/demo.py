"""The demo visit for the open app: time left and whether the visit is over (Phase 7).

The app sends a heartbeat every minute while it is open; that is how a visit's 30 minutes are
counted (closing the tab pauses it). When the visit is over, its Clerk session is revoked so
the visitor is signed out. Demo visits only; anyone else gets 404.
"""

import logging

from eagleeye_core.envelope import ok
from fastapi import APIRouter, Request

from app.auth import AuthedUser, CurrentUser
from app.errors import ApiException
from app.services import demo_visits

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/demo", tags=["demo"])

_revoked: set[str] = set()  # sessions already revoked by this process (revoke once)


def _require_visit(user: AuthedUser) -> str:
    if not user.is_demo or not user.session_id:
        raise ApiException(404, "NOT_FOUND", "Not found.")
    return user.session_id


async def _end_session(request: Request, session_id: str) -> None:
    if session_id in _revoked:
        return
    try:
        await request.app.state.clerk_admin.revoke_session(session_id)
        _revoked.add(session_id)
    except Exception:  # noqa: BLE001 - the app signs out too; this is the server-side backstop
        logger.warning("could not revoke demo session %s", session_id, exc_info=True)


@router.post("/heartbeat")
async def heartbeat(request: Request, user: CurrentUser) -> dict:
    session_id = _require_visit(user)
    state = await demo_visits.heartbeat(request.app.state.pool, session_id)
    if state is None:
        raise ApiException(404, "NOT_FOUND", "This demo session has ended. Sign in again.")
    if state.exhausted:
        await _end_session(request, session_id)
    return ok(
        {
            **state.public(),
            "message": demo_visits.refusal_message(state) if state.exhausted else None,
        }
    )


@router.get("/visit")
async def visit(request: Request, user: CurrentUser) -> dict:
    _require_visit(user)
    state = await demo_visits.state_of(request.app.state.pool, user.id)
    if state is None:
        raise ApiException(404, "NOT_FOUND", "This demo session has ended. Sign in again.")
    return ok(
        {
            **state.public(),
            "message": demo_visits.refusal_message(state) if state.exhausted else None,
        }
    )
