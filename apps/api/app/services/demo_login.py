"""Tell the owner when someone signs in to the shared demo account.

Clerk puts the session id in every token (`sid`). The first request the API sees for a new
demo session claims that id in Redis (SET NX); only that request schedules the email, so a
sign-in sends one message however many requests follow, and however many API processes run.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from eagleeye_core.config import Settings

from app.services.notify import send_email

logger = logging.getLogger(__name__)

SESSION_TTL_S = 7 * 24 * 3600  # Clerk sessions last at most this long by default
USER_AGENT_MAX = 200

# background sends: keep a reference so the task isn't garbage-collected mid-flight
_pending: set[asyncio.Task[Any]] = set()


def compose(when: datetime, ip: str, user_agent: str, username: str) -> tuple[str, str]:
    stamp = when.strftime("%Y-%m-%d %H:%M UTC")
    subject = f"EagleEye demo sign-in · {stamp}"
    body = (
        f"Someone signed in to the EagleEye demo account ({username}).\n\n"
        f"Time:     {stamp}\n"
        f"IP:       {ip}\n"
        f"Browser:  {user_agent[:USER_AGENT_MAX] or 'unknown'}\n\n"
        "You get one email per sign-in session. The demo account has its own LLM spend cap; "
        "see the admin console for its usage.\n"
    )
    return subject, body


async def is_new_session(redis: Any, session_id: str, settings: Settings) -> bool:
    """Claims the session; False if it was seen before or the hourly cap is reached."""
    if not await redis.set(f"demo:session:{session_id}", 1, nx=True, ex=SESSION_TTL_S):
        return False
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    sent = await redis.incr(f"demo:notify:{hour}")
    if sent == 1:
        await redis.expire(f"demo:notify:{hour}", 3600)
    if sent > settings.demo_notify_max_per_hour:
        logger.warning("demo sign-in notifications capped this hour (%s)", sent)
        return False
    return True


async def note_request(
    redis: Any, settings: Settings, claims: dict, ip: str, user_agent: str
) -> None:
    """Called for each authenticated demo request; cheap when the session is known."""
    session_id = claims.get("sid")
    if not settings.demo_notify_email or not session_id or redis is None:
        return
    try:
        if not await is_new_session(redis, str(session_id), settings):
            return
    except Exception:  # Redis down: skip the email rather than fail the request
        logger.warning("demo sign-in check failed", exc_info=True)
        return
    subject, body = compose(datetime.now(UTC), ip, user_agent, settings.demo_username)
    task = asyncio.create_task(send_email(settings, settings.demo_notify_email, subject, body))
    _pending.add(task)
    task.add_done_callback(_pending.discard)
