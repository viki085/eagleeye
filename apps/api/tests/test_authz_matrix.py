"""Authorisation matrix, generated from the app's own route table.

A route added later without authentication (or an admin route without the admin gate) makes
this test fail, instead of relying on someone remembering to add it to a hand-written list.
"""

import re
import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import users as users_repo
from fake_redis import FakeRedis
from fastapi.testclient import TestClient

PUBLIC = {("GET", "/v1/health"), ("GET", "/v1/health/live")}
MEMBER = AuthedUser(str(uuid.uuid4()), "ck_member", "member@corp.com", None, "member")


def _routes() -> list[tuple[str, str]]:
    """Every operation in the OpenAPI schema (FastAPI includes routers lazily, so walking
    app.routes misses them; no route opts out with include_in_schema=False)."""
    paths = create_app().openapi()["paths"]
    return sorted(
        (method.upper(), path)
        for path, ops in paths.items()
        if path.startswith("/v1")
        for method in ops
    )


def _concrete(path: str) -> str:
    """Fill path parameters with well-formed values so validation can't mask the auth check."""
    return re.sub(r"\{[^}]+\}", lambda _m: str(uuid.uuid4()), path)


ROUTES = _routes()
PROTECTED = [r for r in ROUTES if r not in PUBLIC]
ADMIN = [r for r in ROUTES if r[1].startswith("/v1/admin")]


def test_the_matrix_actually_covers_the_app() -> None:
    assert len(PROTECTED) > 30 and len(ADMIN) >= 10  # guards against an empty route scan


@pytest.mark.parametrize(("method", "path"), PROTECTED, ids=[f"{m} {p}" for m, p in PROTECTED])
def test_every_non_public_route_requires_a_token(method: str, path: str) -> None:
    app = create_app()
    app.state.redis = FakeRedis()
    resp = TestClient(app).request(method, _concrete(path))
    assert resp.status_code == 401, f"{method} {path} answered {resp.status_code} without a token"


@pytest.mark.parametrize(("method", "path"), PUBLIC, ids=[f"{m} {p}" for m, p in PUBLIC])
def test_public_routes_stay_public(method: str, path: str) -> None:
    app = create_app()
    resp = TestClient(app, raise_server_exceptions=False).request(method, path)
    assert resp.status_code != 401


@pytest.mark.parametrize(("method", "path"), ADMIN, ids=[f"{m} {p}" for m, p in ADMIN])
def test_every_admin_route_refuses_members(
    method: str, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def member_role(pool, user_id):  # noqa: ANN001, ANN202
        return ("member", "active")

    monkeypatch.setattr(users_repo, "fresh_role", member_role)
    app = create_app()
    app.state.pool = object()
    app.state.redis = FakeRedis()
    app.dependency_overrides[get_current_user] = lambda: MEMBER
    resp = TestClient(app).request(method, _concrete(path), json={})
    assert resp.status_code == 403, f"{method} {path} answered {resp.status_code} for a member"
