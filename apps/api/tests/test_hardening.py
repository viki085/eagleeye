import uuid

import pytest
from app.auth import AuthedUser, get_current_user
from app.errors import ApiException
from app.main import create_app
from app.services import rate_limit
from app.services.rate_limit import Limit, StreamSlots
from fake_redis import FakeRedis
from fastapi.testclient import TestClient

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")


# --- limiter unit tests -----------------------------------------------------------------


async def test_limit_allows_up_to_the_cap_then_429_with_retry_after() -> None:
    redis = FakeRedis()
    limit = Limit("t", 3)
    for _ in range(3):
        await rate_limit.hit(redis, limit, "u1", now=120.0)
    with pytest.raises(ApiException) as exc:
        await rate_limit.hit(redis, limit, "u1", now=125.0)
    assert exc.value.status_code == 429 and exc.value.headers == {"Retry-After": "55"}
    await rate_limit.hit(redis, limit, "u2", now=125.0)  # per subject
    await rate_limit.hit(redis, limit, "u1", now=181.0)  # next window


async def test_limiter_fails_open_when_redis_is_down() -> None:
    for _ in range(10):
        await rate_limit.hit(FakeRedis(fail=True), Limit("t", 1), "u1")


async def test_stream_slots_cap_and_release() -> None:
    redis = FakeRedis()
    first, second = StreamSlots(redis, "u1", 1), StreamSlots(redis, "u1", 1)
    await first.acquire()
    with pytest.raises(ApiException):
        await second.acquire()
    assert redis.data["streams:u1"] == 1  # the refused slot was handed back
    await first.release()
    await first.release()  # idempotent
    assert "streams:u1" not in redis.data
    await second.acquire()


# --- app-level hardening ------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.redis = FakeRedis()
    return TestClient(app, raise_server_exceptions=False)


def test_errors_carry_a_request_id_and_security_headers(client: TestClient) -> None:
    resp = client.get("/v1/documents/not-a-uuid")
    rid = resp.headers["x-request-id"]
    assert resp.status_code == 422 and resp.json()["error"]["request_id"] == rid
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"


def test_incoming_request_id_is_kept_only_when_well_formed(client: TestClient) -> None:
    good = client.get("/v1/documents/x", headers={"X-Request-ID": "abc12345-req"})
    assert good.headers["x-request-id"] == "abc12345-req"
    bad = client.get("/v1/documents/x", headers={"X-Request-ID": "<script>"})
    assert bad.headers["x-request-id"] != "<script>"


def test_large_json_bodies_are_refused_before_reading(client: TestClient) -> None:
    resp = client.post(
        "/v1/chats/c1/messages",
        content=b'{"text": "' + b"x" * 70_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_unhandled_errors_hide_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repos import chats as chats_repo

    async def boom(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(chats_repo, "list_chats", boom)
    client.app.state.pool = object()
    resp = client.get("/v1/chats")
    body = resp.json()
    assert resp.status_code == 500 and body["error"]["code"] == "INTERNAL_ERROR"
    assert "hunter2" not in resp.text and body["error"]["request_id"]
    assert resp.headers["x-request-id"] == body["error"]["request_id"]


def test_crash_response_still_carries_cors_headers(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.repos import chats as chats_repo
    from eagleeye_core.config import get_settings

    async def boom(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("boom")

    monkeypatch.setattr(chats_repo, "list_chats", boom)
    client.app.state.pool = object()
    resp = client.get("/v1/chats", headers={"Origin": get_settings().web_origin})
    assert resp.status_code == 500
    assert resp.headers["access-control-allow-origin"] == get_settings().web_origin


@pytest.mark.parametrize(
    ("switch", "method", "path", "kwargs"),
    [
        (
            "chat",
            "post",
            "/v1/chats/{chat}/messages",
            {"json": {"text": "hi", "idempotency_key": "k-12345678"}},
        ),
        (
            "uploads",
            "post",
            "/v1/documents",
            {"files": {"file": ("a.txt", b"hello", "text/plain")}, "data": {"scope": "personal"}},
        ),
        ("uploads", "post", "/v1/datasets", {"files": {"file": ("a.csv", b"a\n1\n", "text/csv")}}),
    ],
)
def test_kill_switches_refuse_new_work(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    switch: str,
    method: str,
    path: str,
    kwargs: dict,
) -> None:
    from app.repos import chats as chats_repo
    from app.repos import messages as messages_repo

    async def owned(*a):  # noqa: ANN002, ANN202
        return {"id": "c1"}

    async def no_dup(*a):  # noqa: ANN002, ANN202
        return None

    monkeypatch.setattr(chats_repo, "get_owned_chat", owned)
    monkeypatch.setattr(messages_repo, "find_by_idempotency_key", no_dup)
    client.app.state.pool = object()
    client.app.state.redis.data[f"kill:{switch}"] = "admin"
    resp = getattr(client, method)(path.format(chat=uuid.uuid4()), **kwargs)
    assert resp.status_code == 503 and resp.json()["error"]["code"] == "DISABLED"


def test_message_rate_limit_returns_429(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_uploads_per_min", 2)
    for _ in range(2):  # these fail later (unsupported type) but the limit counts them first
        client.post("/v1/datasets", files={"file": ("a.pdf", b"x", "application/pdf")})
    resp = client.post("/v1/datasets", files={"file": ("a.pdf", b"x", "application/pdf")})
    assert resp.status_code == 429 and resp.headers["retry-after"]
    assert resp.json()["error"]["code"] == "RATE_LIMITED"
