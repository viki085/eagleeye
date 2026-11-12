from fastapi import APIRouter

from eagleeye_core.envelope import ok

from app.auth import CurrentUser

router = APIRouter(tags=["me"])


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return ok(
        {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "role": user.role,
        }
    )
