import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import admin_metrics, users
from fake_redis import FakeRedis
from fastapi.testclient import TestClient

ADMIN = AuthedUser(str(uuid.uuid4()), "user_admin", "admin@example.com", None, "admin")
MEMBER = AuthedUser(str(uuid.uuid4()), "user_member", "member@example.com", None, "member")


class FakePool:
    def __init__(self) -> None:
        self.roles: dict[str, tuple[str, str]] = {
            ADMIN.id: ("admin", "active"),
            MEMBER.id: ("member", "active"),
        }
        self.actions: list[tuple] = []

    async def fetchrow(self, sql: str, *args: object):  # noqa: ANN201
        if "FROM users WHERE id" in sql:
            role = self.roles.get(str(args[0]))
            return {"role": role[0], "status": role[1]} if role else None
        return None

    async def execute(self, sql: str, *args: object) -> str:
        if "security_events" in sql:
            self.actions.append(args)
        return "UPDATE 0"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict:
    app = create_app()
    pool = FakePool()
    app.state.pool = pool
    app.state.redis = FakeRedis()

    async def fake_overview(p, w):  # noqa: ANN001, ANN202
        return {"runs": 3}

    async def fake_counts(p, a, b):  # noqa: ANN001, ANN202
        return {"active": 0, "stuck": 0}

    async def fake_checks():  # noqa: ANN202
        return []

    monkeypatch.setattr(admin_metrics, "overview", fake_overview)
    monkeypatch.setattr(admin_metrics, "run_counts", fake_counts)
    monkeypatch.setattr("app.routers.admin.check_all", fake_checks)
    return {"app": app, "pool": pool, "client": TestClient(app)}


def _as(env: dict, user: AuthedUser) -> TestClient:
    env["app"].dependency_overrides[get_current_user] = lambda: user
    return env["client"]


ROUTES = [
    "/v1/admin/overview",
    "/v1/admin/users",
    "/v1/admin/usage",
    "/v1/admin/safety",
    "/v1/admin/content",
    "/v1/admin/system",
]


@pytest.mark.parametrize("path", ROUTES)
def test_members_get_403_on_every_admin_route(env: dict, path: str) -> None:
    resp = _as(env, MEMBER).get(path)
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "FORBIDDEN"


def test_member_cannot_flip_switches_or_clear_runs(env: dict) -> None:
    client = _as(env, MEMBER)
    assert client.post("/v1/admin/switches/sql", json={"killed": True}).status_code == 403
    assert client.post("/v1/admin/runs/clear-stuck").status_code == 403
    assert "kill:sql" not in env["app"].state.redis.data


def test_admin_sees_overview(env: dict) -> None:
    resp = _as(env, ADMIN).get("/v1/admin/overview?range=24h")
    assert resp.status_code == 200 and resp.json()["data"] == {"range": "24h", "runs": 3}
    assert _as(env, ADMIN).get("/v1/admin/overview?range=1y").status_code == 422


def test_demoted_admin_loses_access_immediately(env: dict) -> None:
    client = _as(env, ADMIN)  # the cached identity still says "admin"
    assert client.get("/v1/admin/overview").status_code == 200
    env["pool"].roles[ADMIN.id] = ("member", "active")
    assert client.get("/v1/admin/overview").status_code == 403
    env["pool"].roles[ADMIN.id] = ("admin", "disabled")
    assert client.get("/v1/admin/overview").status_code == 403


def test_switches_flip_redis_flags_and_are_audited(env: dict) -> None:
    client = _as(env, ADMIN)
    assert client.post("/v1/admin/switches/sql", json={"killed": True}).status_code == 200
    assert env["app"].state.redis.data["kill:sql"] == ADMIN.id
    system = client.get("/v1/admin/system").json()["data"]
    assert {"name": "sql", "killed": True}.items() <= system["switches"][1].items()
    client.post("/v1/admin/switches/sql", json={"killed": False})
    assert "kill:sql" not in env["app"].state.redis.data
    categories = [a[1] for a in env["pool"].actions]
    assert categories == ["switch_off", "switch_on"]
    assert client.post("/v1/admin/switches/everything", json={"killed": True}).status_code == 422


def test_me_reports_the_fresh_role_not_the_cached_one(env: dict) -> None:
    assert users  # module used by require_admin
    client = _as(env, MEMBER)  # cached identity says "member"
    assert client.get("/v1/me").json()["data"]["role"] == "member"
    env["pool"].roles[MEMBER.id] = ("admin", "active")  # promoted in the database
    me = client.get("/v1/me").json()["data"]
    assert me["role"] == "admin" and me["can_manage_enterprise"] is True
