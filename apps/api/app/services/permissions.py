"""Who may do what. One place for the rules the API enforces (and /v1/me exposes to the UI)."""

from typing import Annotated

from eagleeye_core.config import get_settings
from fastapi import Depends, Request

from app.auth import AuthedUser, CurrentUser
from app.errors import ApiException

ENTERPRISE_MANAGER_ROLES = frozenset({"knowledge_admin", "admin"})
ADMIN_ROLE = "admin"


def can_manage_enterprise(user: AuthedUser) -> bool:
    """Upload or delete enterprise documents: knowledge admins and admins only, unless the
    deployment explicitly opens it to everyone (ENTERPRISE_UPLOAD_OPEN=true)."""
    return get_settings().enterprise_upload_open or user.role in ENTERPRISE_MANAGER_ROLES


def is_admin(user: AuthedUser) -> bool:
    return user.role == ADMIN_ROLE


async def require_admin(request: Request, user: CurrentUser) -> AuthedUser:
    """Admin console gate. Reads role and status from the database on EVERY call: the auth
    cache keeps a user for 60 s, and a demoted admin must lose access immediately."""
    from app.repos.users import fresh_role  # local import keeps permissions import-light

    current = await fresh_role(request.app.state.pool, user.id)
    if current is None or current[1] != "active" or current[0] != ADMIN_ROLE:
        raise ApiException(403, "FORBIDDEN", "Admins only.")
    return user


AdminUser = Annotated[AuthedUser, Depends(require_admin)]
