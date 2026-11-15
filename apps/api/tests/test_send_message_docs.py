"""Send-message admission: doc authorisation, one active run per chat, per-user cap,
enqueue failures; plus cancel ownership."""

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import asyncpg
import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import chats as chats_repo
from app.repos import documents as docs_repo
from app.repos import messages as messages_repo
from app.repos import runs as runs_repo
from app.repos import usage as usage_repo
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
CHAT_ID = str(uuid.uuid4())
RUN_ID = str(uuid.uuid4())


class _Conn:
    @asynccontextmanager
    async def transaction(self):  # noqa: ANN201
        yield


class _Pool:
    @asynccontextmanager
    async def acquire(self):  # noqa: ANN201
        yield _Conn()


@dataclass
class Env:
    client: TestClient
    queued: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    active_chat: bool = False
    active_user: int = 0
    queue_fails: bool = False
    unique_violation: bool = False
    redis_sets: list[str] = field(default_factory=list)
    run_status: str | None = "RUNNING"
    spent_usd: float = 0.0


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Env:
    app = create_app()
    e = Env(client=TestClient(app))

    async def owned_chat(pool, chat_id, user_id):  # noqa: ANN001
        return {"id": chat_id}

    async def no_duplicate(pool, chat_id, key):  # noqa: ANN001
        return None

    async def only_first_visible(pool, doc_ids, user_id):  # noqa: ANN001
        return set(doc_ids[:1])

    async def fail_stale(pool, user_id):  # noqa: ANN001
        return 0

    async def has_active(pool, chat_id):  # noqa: ANN001
        return e.active_chat

    async def count_active(pool, user_id):  # noqa: ANN001
        return e.active_user

    async def create_run(conn, chat_id, user_id, params):  # noqa: ANN001
        if e.unique_violation:
            raise asyncpg.UniqueViolationError("dup")
        return RUN_ID

    async def insert_user_message(conn, chat_id, text, run_id, key):  # noqa: ANN001
        return {"id": "m1"}

    async def mark_failed(pool, run_id, code):  # noqa: ANN001
        e.failed.append(code)

    async def get_owned_run(pool, run_id, user_id):  # noqa: ANN001
        return None if e.run_status is None else {"id": run_id, "status": e.run_status}

    async def total_cost(pool, user_id):  # noqa: ANN001
        return e.spent_usd

    for mod, name, fn in [
        (chats_repo, "get_owned_chat", owned_chat),
        (messages_repo, "find_by_idempotency_key", no_duplicate),
        (messages_repo, "insert_user_message", insert_user_message),
        (docs_repo, "filter_visible_ready", only_first_visible),
        (runs_repo, "fail_stale_runs", fail_stale),
        (runs_repo, "has_active_run", has_active),
        (runs_repo, "count_active_for_user", count_active),
        (runs_repo, "create_run", create_run),
        (runs_repo, "mark_failed", mark_failed),
        (runs_repo, "get_owned_run", get_owned_run),
        (usage_repo, "total_cost", total_cost),
    ]:
        monkeypatch.setattr(mod, name, fn)

    class Queue:
        async def enqueue_run(self, run_id: str) -> None:
            if e.queue_fails:
                raise RuntimeError("broker down")
            e.queued.append(run_id)

    class Redis:
        async def set(self, key: str, value: str, ex: int) -> None:
            e.redis_sets.append(key)

    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = _Pool()
    app.state.task_queue = Queue()
    app.state.redis = Redis()
    return e


def _send(env: Env, doc_ids: list[str] | None = None):  # noqa: ANN202
    return env.client.post(
        f"/v1/chats/{CHAT_ID}/messages",
        json={"text": "hi", "idempotency_key": "key-12345", "doc_ids": doc_ids or []},
    )


def test_send_enqueues_run(env: Env) -> None:
    resp = _send(env)
    assert resp.status_code == 202 and resp.json()["data"]["run_id"] == RUN_ID
    assert env.queued == [RUN_ID]


def test_inaccessible_doc_ids_are_rejected(env: Env) -> None:
    resp = _send(env, [str(uuid.uuid4()), str(uuid.uuid4())])
    assert resp.status_code == 422 and "not ready" in resp.json()["error"]["message"]


def test_malformed_and_too_many_doc_ids_rejected(env: Env) -> None:
    assert _send(env, ["not-a-uuid"]).status_code == 422
    assert _send(env, [str(uuid.uuid4()) for _ in range(21)]).status_code == 422


def test_active_run_on_chat_is_409(env: Env) -> None:
    env.active_chat = True
    resp = _send(env)
    assert resp.status_code == 409 and "Still answering" in resp.json()["error"]["message"]
    assert env.queued == []


def test_race_on_unique_index_is_409(env: Env) -> None:
    env.unique_violation = True
    assert _send(env).status_code == 409


def test_per_user_cap_is_429(env: Env) -> None:
    env.active_user = 2
    assert _send(env).status_code == 429


def test_usage_limit_reached_is_429_quota(env: Env) -> None:
    env.spent_usd = 500.0
    resp = _send(env)
    assert resp.status_code == 429 and resp.json()["error"]["code"] == "QUOTA_EXCEEDED"
    assert "$500" in resp.json()["error"]["message"] and env.queued == []


def test_usage_endpoint_shape(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import date

    async def totals(pool, user_id):  # noqa: ANN001
        return usage_repo.UsageTotals(1.2345678, 1000, 250, 3)

    async def daily(pool, user_id):  # noqa: ANN001
        return [usage_repo.DailyUsage(date(2026, 11, 12), 0.5, 900)]

    monkeypatch.setattr(usage_repo, "totals", totals)
    monkeypatch.setattr(usage_repo, "daily", daily)
    data = env.client.get("/v1/me/usage").json()["data"]
    assert data["limit_usd"] == 500.0 and data["cost_usd"] == 1.234568
    assert (data["tokens_in"], data["tokens_out"], data["runs"]) == (1000, 250, 3)
    assert data["daily"] == [{"day": "2026-11-12", "cost_usd": 0.5, "tokens": 900}]


def test_enqueue_failure_marks_failed_and_502(env: Env) -> None:
    env.queue_fails = True
    assert _send(env).status_code == 502
    assert env.failed == ["ENQUEUE_FAILED"]


def test_cancel_sets_flag_for_active_run(env: Env) -> None:
    resp = env.client.post(f"/v1/runs/{RUN_ID}/cancel")
    assert resp.status_code == 202 and resp.json()["data"]["cancelled"] is True
    assert env.redis_sets == [f"run:{RUN_ID}:cancel"]


def test_cancel_finished_run_is_noop(env: Env) -> None:
    env.run_status = "SUCCEEDED"
    resp = env.client.post(f"/v1/runs/{RUN_ID}/cancel")
    assert resp.json()["data"]["cancelled"] is False and env.redis_sets == []


def test_cancel_other_users_run_is_404(env: Env) -> None:
    env.run_status = None
    assert env.client.post(f"/v1/runs/{RUN_ID}/cancel").status_code == 404


def test_demo_account_has_its_own_cap_and_message(env: Env) -> None:
    from dataclasses import replace

    demo = replace(ME, is_demo=True, usage_limit_usd=1.0)
    env.client.app.dependency_overrides[get_current_user] = lambda: demo
    env.spent_usd = 0.99
    assert _send(env).status_code == 202
    env.spent_usd = 1.0
    resp = _send(env)
    assert resp.status_code == 429
    assert "demo budget" in resp.json()["error"]["message"]


def test_usage_endpoint_reports_the_users_own_limit(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    async def totals(pool, user_id):  # noqa: ANN001
        return usage_repo.UsageTotals(0.25, 10, 5, 1)

    async def daily(pool, user_id):  # noqa: ANN001
        return []

    monkeypatch.setattr(usage_repo, "totals", totals)
    monkeypatch.setattr(usage_repo, "daily", daily)
    capped = replace(ME, usage_limit_usd=1.0)
    env.client.app.dependency_overrides[get_current_user] = lambda: capped
    assert env.client.get("/v1/me/usage").json()["data"]["limit_usd"] == 1.0
