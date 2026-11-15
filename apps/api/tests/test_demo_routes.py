"""The demo sign-in acts as the session's visit account; the heartbeat ends used-up visits."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app import auth
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.services import demo_visits as dv
from fastapi import HTTPException
from fastapi.testclient import TestClient

BASE = AuthedUser(str(uuid.uuid4()), "user_demo", "demo@example.com", None, "member", is_demo=True)
VISIT_ID = str(uuid.uuid4())


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(pool=object())),
        client=SimpleNamespace(host="203.0.113.7"),
    )


@pytest.fixture
def visits(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    calls: list[tuple] = []

    async def account_for_session(pool, base_id, sid, ip):  # noqa: ANN001, ANN202
        calls.append((base_id, sid, ip))
        return VISIT_ID

    async def get_user(pool, user_id):  # noqa: ANN001, ANN202
        return {"id": user_id, "display_name": "Demo visitor", "usage_limit_usd": 0.5}

    from app.repos import users as users_repo

    monkeypatch.setattr(dv, "account_for_session", account_for_session)
    monkeypatch.setattr(users_repo, "get_user", get_user)
    auth._visit_cache._items.clear()  # noqa: SLF001
    return calls


async def test_demo_sign_in_acts_as_the_visit_account(visits: list[tuple]) -> None:
    user = await auth._as_demo_visit(_request(), BASE, {"sid": "sess_1"})  # noqa: SLF001
    assert user.id == VISIT_ID and user.is_demo and user.session_id == "sess_1"
    assert user.usage_limit_usd == 0.5 and user.role == "member"
    assert visits == [(BASE.id, "sess_1", "203.0.113.7")]
    await auth._as_demo_visit(_request(), BASE, {"sid": "sess_1"})  # noqa: SLF001
    assert len(visits) == 1  # cached per session


async def test_other_users_are_unchanged(visits: list[tuple]) -> None:
    member = replace(BASE, is_demo=False)
    assert await auth._as_demo_visit(_request(), member, {"sid": "s"}) is member  # noqa: SLF001
    assert visits == []


async def test_a_demo_token_without_a_session_is_refused(visits: list[tuple]) -> None:
    with pytest.raises(HTTPException) as exc:
        await auth._as_demo_visit(_request(), BASE, {})  # noqa: SLF001
    assert exc.value.status_code == 401


# ---- /v1/demo -------------------------------------------------------------------------------

VISITOR = replace(BASE, id=VISIT_ID, session_id="sess_9")


def _state(exhausted: str | None) -> dv.VisitState:
    now = datetime.now(UTC)
    return dv.VisitState(
        VISIT_ID,
        VISIT_ID,
        0 if exhausted else 900,
        0.3,
        now + timedelta(hours=20),
        exhausted,
        now + timedelta(hours=20) if exhausted else None,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: VISITOR
    revoked: list[str] = []

    class Clerk:
        async def revoke_session(self, sid: str) -> None:
            revoked.append(sid)

    app.state.pool = object()
    app.state.clerk_admin = Clerk()
    app.state.revoked = revoked
    from app.routers import demo as demo_router

    demo_router._revoked.clear()  # noqa: SLF001
    return TestClient(app)


def test_heartbeat_reports_time_left(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def heartbeat(pool, sid):  # noqa: ANN001, ANN202
        return _state(None)

    monkeypatch.setattr(dv, "heartbeat", heartbeat)
    data = client.post("/v1/demo/heartbeat").json()["data"]
    assert data == {"seconds_left": 900, "exhausted": None, "available_at": None, "message": None}
    assert client.app.state.revoked == []


def test_a_used_up_visit_is_signed_out_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def heartbeat(pool, sid):  # noqa: ANN001, ANN202
        return _state("time")

    monkeypatch.setattr(dv, "heartbeat", heartbeat)
    for _ in range(2):
        data = client.post("/v1/demo/heartbeat").json()["data"]
    assert data["exhausted"] == "time" and "30 minutes" in data["message"]
    assert "budget" not in data and "spent" not in str(data)  # no money figures for the app
    assert client.app.state.revoked == ["sess_9"]


def test_not_for_regular_users(client: TestClient) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: replace(BASE, is_demo=False)
    assert client.post("/v1/demo/heartbeat").status_code == 404
    assert client.get("/v1/demo/visit").status_code == 404


def test_send_is_refused_when_the_visit_is_used_up(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import chats as chats_router

    async def state_of(pool, user_id):  # noqa: ANN001, ANN202
        return _state("daily")

    monkeypatch.setattr(dv, "state_of", state_of)

    async def run() -> None:
        await chats_router._admit_run(SimpleNamespace(), "chat", VISITOR)  # noqa: SLF001

    for name in ("fail_stale_runs", "has_active_run", "count_active_for_user"):

        async def stub(*a, _n=name):  # noqa: ANN002, ANN202
            return 0 if _n != "has_active_run" else False

        monkeypatch.setattr(chats_router.runs_repo, name, stub)
    import asyncio

    from app.errors import ApiException

    with pytest.raises(ApiException) as exc:
        asyncio.run(run())
    assert exc.value.status_code == 429 and "today's limit" in str(exc.value.message)
