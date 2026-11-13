"""Data sources the caller's role may query — names and descriptions only (LLD §2.2)."""

from eagleeye_core.config import get_settings
from eagleeye_core.envelope import ok
from fastapi import APIRouter, Request

from app.auth import CurrentUser

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
async def list_sources(request: Request, user: CurrentUser) -> dict:
    if not get_settings().enable_sql:
        return ok([])
    sources = await request.app.state.catalog.accessible_sources(user.role)
    return ok(
        [
            {
                "id": acc.source.id,
                "name": acc.source.name,
                "description": acc.source.description,
                "can_see_pii": acc.grant.can_see_pii,
                "tables": [
                    {"name": t.key, "description": t.description, "row_estimate": t.row_estimate}
                    for t in acc.tables
                ],
            }
            for acc in sources
        ]
    )
