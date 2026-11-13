"""Route guards: kill switches and per-action rate limits, one line per route."""

from eagleeye_core.config import get_settings
from eagleeye_core.switches import Switch, is_killed
from fastapi import Request

from app.auth import AuthedUser
from app.errors import ApiException
from app.services import rate_limit
from app.services.rate_limit import Limit

SWITCHED_OFF = {
    "chat": "New questions are paused by an administrator. Try again later.",
    "uploads": "Uploads are paused by an administrator. Try again later.",
}


async def ensure_enabled(request: Request, switch: Switch) -> None:
    redis = getattr(request.app.state, "redis", None)
    if redis is not None and await is_killed(redis, switch):
        raise ApiException(503, "DISABLED", SWITCHED_OFF.get(switch, "This feature is paused."))


async def limit_action(request: Request, user: AuthedUser, action: str) -> None:
    """`action`: "messages" or "uploads" — on top of the general per-user limit."""
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    s = get_settings()
    per_minute = {
        "messages": s.rate_limit_messages_per_min,
        "uploads": s.rate_limit_uploads_per_min,
    }[action]
    await rate_limit.hit(redis, Limit(action, per_minute), user.id)
