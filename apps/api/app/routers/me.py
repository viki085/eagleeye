from dataclasses import replace

from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from fastapi import APIRouter, Request

from app.auth import CurrentUser, usage_limit_for
from app.repos import usage as usage_repo
from app.repos.users import fresh_role
from app.services.permissions import can_manage_enterprise

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(request: Request, user: CurrentUser) -> dict:
    # role read fresh (the auth cache keeps a user for 60 s) so the UI matches what the admin
    # and enterprise checks will decide right now
    current = await fresh_role(request.app.state.pool, user.id)
    role = current[0] if current else user.role
    effective = replace(user, role=role)
    return ok(
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": role,
            # the UI hides enterprise upload/delete when false; the API enforces it regardless
            "can_manage_enterprise": can_manage_enterprise(effective),
            # shared public demo account: the UI shows the demo banner and suggested questions
            "is_demo": user.is_demo,
        }
    )


@router.get("/me/usage")
async def my_usage(request: Request, user: CurrentUser) -> dict:
    pool = request.app.state.pool
    totals = await usage_repo.totals(pool, user.id)
    days = await usage_repo.daily(pool, user.id)
    return ok(
        {
            # demo visitors are never told the money limits (the app shows them time only)
            "limit_usd": None
            if user.is_demo
            else usage_limit_for(user, get_settings().usage_limit_usd),
            "cost_usd": round(totals.cost_usd, 6),
            "tokens_in": totals.tokens_in,
            "tokens_out": totals.tokens_out,
            "runs": totals.runs,
            "daily": [
                {"day": d.day.isoformat(), "cost_usd": round(d.cost_usd, 6), "tokens": d.tokens}
                for d in days
            ],
        }
    )
