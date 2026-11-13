from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from fastapi import APIRouter, Request

from app.auth import CurrentUser
from app.repos import usage as usage_repo
from app.services.permissions import can_manage_enterprise

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return ok(
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
            # the UI hides enterprise upload/delete when false; the API enforces it regardless
            "can_manage_enterprise": can_manage_enterprise(user),
        }
    )


@router.get("/me/usage")
async def my_usage(request: Request, user: CurrentUser) -> dict:
    pool = request.app.state.pool
    totals = await usage_repo.totals(pool, user.id)
    days = await usage_repo.daily(pool, user.id)
    return ok(
        {
            "limit_usd": get_settings().usage_limit_usd,
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
