import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import admin_metrics, admin_overview, users
from app.services.health_checks import ServiceHealth
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
        self.settings: dict[str, str] = {}

    async def fetchval(self, sql: str, *args: object):  # noqa: ANN201
        if "FROM app_settings" in sql:
            return self.settings.get(str(args[0]))
        return None

    async def fetchrow(self, sql: str, *args: object):  # noqa: ANN201
        if "FROM users WHERE id" in sql:
            role = self.roles.get(str(args[0]))
            return {"role": role[0], "status": role[1]} if role else None
        return None

    async def execute(self, sql: str, *args: object) -> str:
        if "security_events" in sql:
            self.actions.append(args)
        if "INSERT INTO app_settings" in sql:
            self.settings[str(args[0])] = str(args[1])
        return "UPDATE 0"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict:
    app = create_app()
    pool = FakePool()
    app.state.pool = pool
    app.state.redis = FakeRedis()

    overview_calls: list[str] = []

    async def fake_overview(p, w, budget_usd=0.0):  # noqa: ANN001, ANN202
        overview_calls.append(f"{w.span}|{budget_usd}")
        return {"current": {"requests": 3}, "series": [], "budget": budget_usd}

    async def fake_counts(p, a, b):  # noqa: ANN001, ANN202
        return {"active": 2, "stuck": 0}

    async def fake_checks():  # noqa: ANN202
        return []

    async def fake_databases():  # noqa: ANN202
        return [ServiceHealth("supabase-pg", "up", 7), ServiceHealth("qdrant", "up", 20)]

    monkeypatch.setattr(admin_overview, "overview", fake_overview)
    monkeypatch.setattr(admin_metrics, "run_counts", fake_counts)
    monkeypatch.setattr("app.routers.admin.check_all", fake_checks)
    monkeypatch.setattr("app.routers.admin.check_databases", fake_databases)
    return {"app": app, "pool": pool, "client": TestClient(app), "overview_calls": overview_calls}


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


def test_admin_sees_overview_with_live_status(env: dict) -> None:
    resp = _as(env, ADMIN).get("/v1/admin/overview?range=24h")
    data = resp.json()["data"]
    assert resp.status_code == 200 and data["range"] == "24h"
    assert data["current"] == {"requests": 3} and data["generated_at"]
    assert data["live"]["agents"] == {"active": 2, "stuck": 0}
    assert data["live"]["databases"]["status"] == "healthy"
    assert _as(env, ADMIN).get("/v1/admin/overview?range=1y").status_code == 422


def test_overview_aggregates_are_cached_per_range(env: dict) -> None:
    client = _as(env, ADMIN)
    for _ in range(3):
        client.get("/v1/admin/overview?range=7d")
    client.get("/v1/admin/overview?range=24h")
    assert len(env["overview_calls"]) == 2  # one query per range, then served from cache
    assert "admin:overview:7d" in env["app"].state.redis.data


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


def test_overview_reports_app_cache_figures(env: dict) -> None:
    from datetime import UTC, datetime

    from eagleeye_core.app_cache import stats_key

    env["app"].state.redis.data[stats_key(datetime.now(UTC))] = {
        b"answer:lookups": b"4",
        b"answer:hits": b"1",
        b"answer:saved_usd": b"0.02",
        b"guard:lookups": b"4",
        b"guard:hits": b"3",
    }
    caching = _as(env, ADMIN).get("/v1/admin/overview?range=24h").json()["data"]["caching"]
    assert caching["lookups"] == 8 and caching["hits"] == 4 and caching["hit_rate"] == 0.5
    assert caching["saved_usd"] == 0.02
    assert caching["by_kind"]["answer"] == {"lookups": 4, "hits": 1, "saved_usd": 0.02}


def test_admin_changes_the_monthly_budget_and_it_is_audited(env: dict) -> None:
    client = _as(env, ADMIN)
    assert client.get("/v1/admin/overview?range=7d").json()["data"]["budget"] == 100.0
    resp = client.patch("/v1/admin/settings/monthly-budget", json={"budget_usd": 250.456})
    assert resp.status_code == 200 and resp.json()["data"]["budget_usd"] == 250.46
    assert "admin:overview:7d" not in env["app"].state.redis.data  # cached overview dropped
    assert client.get("/v1/admin/overview?range=7d").json()["data"]["budget"] == 250.46
    category, detail = env["pool"].actions[-1][1], env["pool"].actions[-1][2]
    assert category == "monthly_budget_changed" and detail == {"from_usd": 100.0, "to_usd": 250.46}


@pytest.mark.parametrize("value", [0, -5, 2_000_000, "abc"])
def test_invalid_budgets_are_rejected(env: dict, value: object) -> None:
    resp = _as(env, ADMIN).patch("/v1/admin/settings/monthly-budget", json={"budget_usd": value})
    assert resp.status_code == 422 and env["pool"].settings == {}


def test_members_cannot_change_the_budget(env: dict) -> None:
    resp = _as(env, MEMBER).patch("/v1/admin/settings/monthly-budget", json={"budget_usd": 5})
    assert resp.status_code == 403 and env["pool"].settings == {}
