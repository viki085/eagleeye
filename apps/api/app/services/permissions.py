"""Who may change shared (enterprise) content. One rule, used by the API and exposed to the UI."""

from eagleeye_core.config import get_settings

from app.auth import AuthedUser

ENTERPRISE_MANAGER_ROLES = frozenset({"knowledge_admin", "admin"})


def can_manage_enterprise(user: AuthedUser) -> bool:
    """Upload or delete enterprise documents: knowledge admins and admins only, unless the
    deployment explicitly opens it to everyone (ENTERPRISE_UPLOAD_OPEN=true)."""
    return get_settings().enterprise_upload_open or user.role in ENTERPRISE_MANAGER_ROLES
