"""Admin user management: add one, add many (CSV imported by the console in batches), delete.

Every account gets a Clerk sign-in plus an EagleEye row with a role. Deleting revokes the
Clerk sign-in and marks the row deleted (history kept). Actions are audited.
"""

import logging
import re
from typing import Any, Literal
from uuid import UUID

from eagleeye_core.envelope import ok
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.auth import forget_user
from app.errors import ApiException
from app.repos import admin_metrics
from app.repos import users as users_repo
from app.services.clerk_admin import ClerkError
from app.services.permissions import AdminUser

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/users", tags=["admin"])

MAX_BULK = 25  # rows per request; the console sends a CSV in batches of this size
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
Role = Literal["member", "knowledge_admin", "data_admin", "admin"]


USERNAME_RE = re.compile(r"^[a-z0-9_-]{4,64}$")


class NewUser(BaseModel):
    email: str = Field(max_length=254)
    username: str | None = Field(None, max_length=64)  # empty: derived from the email
    first_name: str = Field("", max_length=100)
    last_name: str = Field("", max_length=100)
    role: Role = "member"

    @field_validator("username")
    @classmethod
    def _username(cls, value: str | None) -> str | None:
        name = (value or "").strip().lower()
        if not name:
            return None
        if not USERNAME_RE.match(name):
            raise ValueError("Usernames are 4-64 letters, digits, '_' or '-'.")
        return name

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("Enter a valid email address.")
        return email

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return " ".join(value.split())

    @property
    def display_name(self) -> str | None:
        return f"{self.first_name} {self.last_name}".strip() or None


class BulkUsers(BaseModel):
    users: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_BULK)


async def _add(request: Request, admin: AdminUser, new: NewUser) -> dict[str, Any]:
    state = request.app.state
    existing = await users_repo.find_by_email(state.pool, new.email)
    if existing is not None and existing["status"] != "deleted":
        raise ApiException(409, "CONFLICT", f"A user with {new.email} already exists.")
    try:
        clerk_id, created, username = await state.clerk_admin.create_user(
            new.email, new.first_name, new.last_name, username=new.username
        )
    except ClerkError as exc:
        raise ApiException(
            exc.status if exc.status in (422, 429) else 502, "UPSTREAM_ERROR", exc.message
        ) from exc
    try:
        await state.clerk_admin.add_to_organization(clerk_id)
    except ClerkError as exc:
        await _undo_clerk(state, clerk_id, created)
        raise ApiException(502, "UPSTREAM_ERROR", exc.message) from exc
    try:
        row = await users_repo.provision(
            state.pool,
            clerk_user_id=clerk_id,
            email=new.email,
            display_name=new.display_name,
            role=new.role,
            created_by=admin.id,
            username=username,
            reactivate_id=str(existing["id"]) if existing is not None else None,
        )
    except Exception:
        logger.exception("provisioning %s failed after Clerk account %s", new.email, clerk_id)
        await _undo_clerk(state, clerk_id, created)
        raise
    return users_repo.public(row)


async def _undo_clerk(state: Any, clerk_id: str, created: bool) -> None:
    """Undo only what we created; a pre-existing Clerk account is left alone."""
    if not created:
        return
    try:
        await state.clerk_admin.delete_user(clerk_id)
    except ClerkError:
        logger.error("could not roll back Clerk account %s", clerk_id)


@router.post("", status_code=201)
async def add_user(body: NewUser, request: Request, admin: AdminUser) -> dict:
    user = await _add(request, admin, body)
    await admin_metrics.record_admin_action(
        request.app.state.pool, admin.id, "user_added", {"email": body.email, "role": body.role}
    )
    return ok(user)


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    field = ".".join(str(p) for p in err.get("loc", ())) or "row"
    return f"{field}: {str(err.get('msg', 'invalid')).removeprefix('Value error, ')}"


@router.post("/bulk")
async def add_users(body: BulkUsers, request: Request, admin: AdminUser) -> dict:
    """Per-row results; one bad row never blocks the others."""
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in body.users:
        email = str(raw.get("email", "")).strip().lower()
        try:
            new = NewUser.model_validate(raw)
        except ValidationError as exc:
            results.append({"email": email, "ok": False, "error": _first_error(exc)})
            continue
        if new.email in seen:
            results.append(
                {"email": new.email, "ok": False, "error": "Duplicate row in this file."}
            )
            continue
        seen.add(new.email)
        try:
            user = await _add(request, admin, new)
            results.append({"email": new.email, "ok": True, "user": user})
        except ApiException as exc:
            results.append({"email": new.email, "ok": False, "error": exc.message})
        except Exception:
            results.append({"email": new.email, "ok": False, "error": "Could not add this user."})
    added = sum(1 for r in results if r["ok"])
    await admin_metrics.record_admin_action(
        request.app.state.pool,
        admin.id,
        "users_imported",
        {"added": added, "failed": len(results) - added},
    )
    return ok({"results": results})


@router.delete("/{user_id}")
async def delete_user(user_id: UUID, request: Request, admin: AdminUser) -> dict:
    state = request.app.state
    target = await users_repo.get_user(state.pool, str(user_id))
    if target is None:
        raise ApiException(404, "NOT_FOUND", "User not found.")
    if str(target["id"]) == admin.id:
        raise ApiException(400, "BAD_REQUEST", "You can't delete your own account.")
    if target["role"] == "admin" and target["status"] == "active":
        if await users_repo.active_admin_count(state.pool) <= 1:
            raise ApiException(409, "CONFLICT", "You can't delete the last administrator.")
    # audit first: if the audit write fails, nothing is removed unrecorded
    await admin_metrics.record_admin_action(
        state.pool, admin.id, "user_deleted", {"email": target["email"]}
    )
    try:
        await state.clerk_admin.delete_user(target["clerk_user_id"])
    except ClerkError as exc:
        raise ApiException(502, "UPSTREAM_ERROR", exc.message) from exc
    await users_repo.mark_deleted(state.pool, str(target["id"]))
    forget_user(target["clerk_user_id"])
    return ok({"id": str(target["id"]), "deleted": True})
