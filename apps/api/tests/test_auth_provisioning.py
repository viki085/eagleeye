"""Enterprise sign-in: only accounts an admin provisioned can use the API (no self-signup)."""

import pytest
from app import auth
from app.repos import users as users_repo
from fastapi import HTTPException
from starlette.requests import Request


class Verifier:
    def verify(self, token: str) -> dict:
        return {"sub": token}


def _request() -> Request:
    from types import SimpleNamespace

    scope = {
        "type": "http",
        "headers": [],
        "client": ("127.0.0.1", 1),
        "app": SimpleNamespace(state=SimpleNamespace(pool=object(), redis=None)),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "get_verifier", lambda: Verifier())
    monkeypatch.setattr(auth, "_user_cache", auth._TtlCache(60))


async def test_unprovisioned_clerk_account_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(pool, clerk_user_id):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(users_repo, "touch_signed_in_user", none)
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(_request(), "Bearer ck_stranger")
    assert exc.value.status_code == 403 and "administrator" in str(exc.value.detail)


@pytest.mark.parametrize("status", ["deleted", "disabled"])
async def test_deleted_or_disabled_accounts_are_refused(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    async def row(pool, clerk_user_id):  # noqa: ANN001, ANN202
        return {
            "id": "u1",
            "email": "a@b.co",
            "display_name": None,
            "role": "member",
            "status": status,
        }

    monkeypatch.setattr(users_repo, "touch_signed_in_user", row)
    with pytest.raises(HTTPException) as exc:
        await auth.get_current_user(_request(), "Bearer ck_gone")
    assert exc.value.status_code == 403


async def test_provisioned_account_signs_in(monkeypatch: pytest.MonkeyPatch) -> None:
    async def row(pool, clerk_user_id):  # noqa: ANN001, ANN202
        return {
            "id": "u1",
            "email": "a@b.co",
            "display_name": None,
            "role": "member",
            "status": "active",
        }

    monkeypatch.setattr(users_repo, "touch_signed_in_user", row)
    user = await auth.get_current_user(_request(), "Bearer ck_known")
    assert user.id == "u1" and user.clerk_user_id == "ck_known"


def test_forget_drops_a_cached_identity() -> None:
    auth._user_cache.put("ck_x", auth.AuthedUser("u", "ck_x", "e", None, "member"))
    auth.forget_user("ck_x")
    assert auth._user_cache.get("ck_x") is None
