import uuid

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import chats as chats_repo
from app.repos import documents as docs_repo
from app.repos import messages as messages_repo

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
CHAT_ID = str(uuid.uuid4())


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    async def owned_chat(pool, chat_id, user_id):  # noqa: ANN001
        return {"id": chat_id}

    async def no_duplicate(pool, chat_id, key):  # noqa: ANN001
        return None

    async def only_first_visible(pool, doc_ids, user_id):  # noqa: ANN001
        return set(doc_ids[:1])

    monkeypatch.setattr(chats_repo, "get_owned_chat", owned_chat)
    monkeypatch.setattr(messages_repo, "find_by_idempotency_key", no_duplicate)
    monkeypatch.setattr(docs_repo, "filter_visible_ready", only_first_visible)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = object()
    return TestClient(app)


def _send(client: TestClient, doc_ids: list[str]):  # noqa: ANN202
    return client.post(
        f"/v1/chats/{CHAT_ID}/messages",
        json={"text": "hi", "idempotency_key": "key-12345", "doc_ids": doc_ids},
    )


def test_inaccessible_doc_ids_are_rejected(client: TestClient) -> None:
    resp = _send(client, [str(uuid.uuid4()), str(uuid.uuid4())])
    assert resp.status_code == 422
    assert "not ready" in resp.json()["error"]["message"]


def test_malformed_doc_id_is_rejected(client: TestClient) -> None:
    assert _send(client, ["not-a-uuid"]).status_code == 422


def test_too_many_doc_ids_rejected(client: TestClient) -> None:
    assert _send(client, [str(uuid.uuid4()) for _ in range(21)]).status_code == 422
