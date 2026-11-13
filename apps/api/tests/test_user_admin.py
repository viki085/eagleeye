"""Admin user management: add (one or bulk), delete with guards, Clerk kept in step."""

import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import admin_metrics
from app.repos import users as users_repo
from app.services.clerk_admin import ClerkError
from fake_redis import FakeRedis
from fastapi.testclient import TestClient

ADMIN = AuthedUser(str(uuid.uuid4()), "ck_admin", "admin@corp.com", None, "admin")
MEMBER = AuthedUser(str(uuid.uuid4()), "ck_member", "member@corp.com", None, "member")


class FakeClerk:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.fail_create = False
        self.fail_delete = False
        self.fail_org = False
        self.org_members: list[str] = []
        self.usernames: list[str | None] = []
        self.existing: dict[str, str] = {}  # email -> clerk id already in Clerk

    async def create_user(
        self, email: str, first_name: str, last_name: str, username: str | None = None
    ) -> tuple[str, bool, str | None]:
        if self.fail_create:
            raise ClerkError(502, "Clerk unavailable")
        if email in self.existing:
            return self.existing[email], False, None
        self.created.append(email)
        self.usernames.append(username)
        return f"ck_{email}", True, username

    async def add_to_organization(self, clerk_user_id: str) -> None:
        if self.fail_org:
            raise ClerkError(502, "Could not add the user to the organisation.")
        self.org_members.append(clerk_user_id)

    async def delete_user(self, clerk_user_id: str) -> None:
        if self.fail_delete:
            raise ClerkError(502, "Clerk unavailable")
        self.deleted.append(clerk_user_id)


class FakeUsers:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {
            ADMIN.id: _row(ADMIN.id, ADMIN.email, "admin", ADMIN.clerk_user_id),
            MEMBER.id: _row(MEMBER.id, MEMBER.email, "member", MEMBER.clerk_user_id),
        }
        self.fail_provision = False

    async def find_by_email(self, pool, email):  # noqa: ANN001, ANN201
        return next((r for r in self.rows.values() if r["email"] == email), None)

    async def get_user(self, pool, user_id):  # noqa: ANN001, ANN201
        return self.rows.get(user_id)

    async def provision(
        self,
        pool,
        *,
        clerk_user_id,
        email,
        display_name,
        role,
        created_by,
        username=None,
        reactivate_id=None,
    ):  # noqa: ANN001, ANN201
        if self.fail_provision:
            raise RuntimeError("db down")
        uid = reactivate_id or str(uuid.uuid4())
        self.rows[uid] = _row(uid, email, role, clerk_user_id) | {
            "display_name": display_name,
            "username": username,
        }
        return self.rows[uid]

    async def mark_deleted(self, pool, user_id):  # noqa: ANN001, ANN201
        self.rows[user_id] = self.rows[user_id] | {"status": "deleted"}

    async def active_admin_count(self, pool):  # noqa: ANN001, ANN201
        return sum(
            1 for r in self.rows.values() if r["role"] == "admin" and r["status"] == "active"
        )

    async def fresh_role(self, pool, user_id):  # noqa: ANN001, ANN201
        r = self.rows.get(user_id)
        return (r["role"], r["status"]) if r else None


def _row(uid: str, email: str, role: str, clerk_id: str) -> dict:
    return {
        "id": uid,
        "email": email,
        "role": role,
        "status": "active",
        "display_name": None,
        "clerk_user_id": clerk_id,
        "created_at": None,
        "last_seen_at": None,
    }


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict:
    users = FakeUsers()
    for name in (
        "find_by_email",
        "get_user",
        "provision",
        "mark_deleted",
        "active_admin_count",
        "fresh_role",
    ):
        monkeypatch.setattr(users_repo, name, getattr(users, name))
    audit: list[tuple[str, dict]] = []

    async def record(pool, user_id, category, detail):  # noqa: ANN001, ANN202
        audit.append((category, detail))

    monkeypatch.setattr(admin_metrics, "record_admin_action", record)
    app = create_app()
    app.state.pool = object()
    app.state.redis = FakeRedis()
    app.state.clerk_admin = FakeClerk()
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    return {
        "client": TestClient(app),
        "users": users,
        "clerk": app.state.clerk_admin,
        "audit": audit,
        "app": app,
    }


def test_admin_adds_a_user_in_clerk_and_locally(env: dict) -> None:
    resp = env["client"].post(
        "/v1/admin/users",
        json={
            "email": " New.Person@Corp.com ",
            "first_name": "New",
            "last_name": "Person",
            "role": "knowledge_admin",
        },
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["email"] == "new.person@corp.com" and data["role"] == "knowledge_admin"
    assert env["clerk"].created == ["new.person@corp.com"]
    assert env["audit"] == [
        ("user_added", {"email": "new.person@corp.com", "role": "knowledge_admin"})
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email"},
        {"email": "a@b.co", "role": "superuser"},
        {"email": "a@b.co", "first_name": "x" * 101},
    ],
)
def test_invalid_input_is_rejected_before_clerk(env: dict, body: dict) -> None:
    assert env["client"].post("/v1/admin/users", json=body).status_code == 422
    assert env["clerk"].created == []


def test_duplicate_active_email_is_409(env: dict) -> None:
    resp = env["client"].post("/v1/admin/users", json={"email": "MEMBER@corp.com"})
    assert resp.status_code == 409 and env["clerk"].created == []


def test_readding_a_deleted_user_reactivates_the_account(env: dict) -> None:
    env["users"].rows[MEMBER.id]["status"] = "deleted"
    resp = env["client"].post("/v1/admin/users", json={"email": "member@corp.com"})
    assert resp.status_code == 201 and resp.json()["data"]["id"] == MEMBER.id


def test_new_users_join_the_company_organization(env: dict) -> None:
    env["client"].post("/v1/admin/users", json={"email": "org@corp.com"})
    assert env["clerk"].org_members == ["ck_org@corp.com"]


def test_organization_failure_rolls_back_the_new_clerk_account(env: dict) -> None:
    env["clerk"].fail_org = True
    resp = env["client"].post("/v1/admin/users", json={"email": "org@corp.com"})
    assert resp.status_code == 502
    assert env["clerk"].deleted == ["ck_org@corp.com"]
    assert all(r["email"] != "org@corp.com" for r in env["users"].rows.values())


def test_username_is_passed_through_and_stored(env: dict) -> None:
    resp = env["client"].post("/v1/admin/users", json={"email": "j@corp.com", "username": "Jane_D"})
    assert resp.status_code == 201 and resp.json()["data"]["username"] == "jane_d"
    assert env["clerk"].usernames == ["jane_d"]


@pytest.mark.parametrize("bad", ["ab", "has space", "dots.not.ok", "x" * 65, "émile"])
def test_invalid_usernames_are_rejected(env: dict, bad: str) -> None:
    resp = env["client"].post("/v1/admin/users", json={"email": "j@corp.com", "username": bad})
    assert resp.status_code == 422 and env["clerk"].created == []


def test_clerk_failure_stores_nothing(env: dict) -> None:
    env["clerk"].fail_create = True
    resp = env["client"].post("/v1/admin/users", json={"email": "x@corp.com"})
    assert resp.status_code == 502
    assert env["users"].rows.keys() == {ADMIN.id, MEMBER.id}


def test_database_failure_removes_the_clerk_user_it_just_created(env: dict) -> None:
    env["users"].fail_provision = True
    resp = env["client"].post("/v1/admin/users", json={"email": "x@corp.com"})
    assert resp.status_code == 500
    assert env["clerk"].deleted == ["ck_x@corp.com"]


def test_existing_clerk_account_is_reused_not_deleted_on_failure(env: dict) -> None:
    env["clerk"].existing["x@corp.com"] = "ck_preexisting"
    env["users"].fail_provision = True
    env["client"].post("/v1/admin/users", json={"email": "x@corp.com"})
    assert env["clerk"].deleted == []  # we did not create it, so we must not delete it


def test_bulk_add_reports_each_row(env: dict) -> None:
    resp = env["client"].post(
        "/v1/admin/users/bulk",
        json={
            "users": [
                {"email": "one@corp.com"},
                {"email": "bad"},
                {"email": "member@corp.com"},
                {"email": "ONE@corp.com"},
            ]
        },
    )
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert [r["ok"] for r in results] == [True, False, False, False]
    assert "duplicate" in results[3]["error"].lower()
    assert env["audit"][-1] == ("users_imported", {"added": 1, "failed": 3})


def test_bulk_add_caps_rows_per_request(env: dict) -> None:
    rows = [{"email": f"u{i}@corp.com"} for i in range(26)]
    assert env["client"].post("/v1/admin/users/bulk", json={"users": rows}).status_code == 422


def test_delete_revokes_clerk_access_and_keeps_a_record(env: dict) -> None:
    resp = env["client"].delete(f"/v1/admin/users/{MEMBER.id}")
    assert resp.status_code == 200
    assert env["clerk"].deleted == [MEMBER.clerk_user_id]
    assert env["users"].rows[MEMBER.id]["status"] == "deleted"
    assert env["audit"][0] == ("user_deleted", {"email": MEMBER.email})


def test_cannot_delete_yourself(env: dict) -> None:
    assert env["client"].delete(f"/v1/admin/users/{ADMIN.id}").status_code == 400
    assert env["clerk"].deleted == []


def test_another_admin_can_be_deleted_while_admins_remain(env: dict) -> None:
    other = str(uuid.uuid4())
    env["users"].rows[other] = _row(other, "boss@corp.com", "admin", "ck_boss")
    assert env["client"].delete(f"/v1/admin/users/{other}").status_code == 200  # 2 admins


def test_last_admin_guard(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    peer = str(uuid.uuid4())
    env["users"].rows[peer] = _row(peer, "peer@corp.com", "admin", "ck_peer")

    async def one(pool):  # noqa: ANN001, ANN202
        return 1

    monkeypatch.setattr(users_repo, "active_admin_count", one)
    resp = env["client"].delete(f"/v1/admin/users/{peer}")
    assert resp.status_code == 409 and env["clerk"].deleted == []


def test_clerk_delete_failure_leaves_the_account_active(env: dict) -> None:
    env["clerk"].fail_delete = True
    assert env["client"].delete(f"/v1/admin/users/{MEMBER.id}").status_code == 502
    assert env["users"].rows[MEMBER.id]["status"] == "active"


def test_unknown_user_is_404(env: dict) -> None:
    assert env["client"].delete(f"/v1/admin/users/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/v1/admin/users"),
        ("post", "/v1/admin/users/bulk"),
        ("delete", f"/v1/admin/users/{uuid.uuid4()}"),
    ],
)
def test_members_cannot_manage_users(env: dict, method: str, path: str) -> None:
    env["app"].dependency_overrides[get_current_user] = lambda: MEMBER
    resp = getattr(env["client"], method)(
        path, **({"json": {"email": "a@b.co", "users": []}} if method == "post" else {})
    )
    assert resp.status_code == 403
    assert env["clerk"].created == [] and env["clerk"].deleted == []
