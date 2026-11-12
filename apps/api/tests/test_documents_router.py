import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import documents as docs_repo

ME = AuthedUser(str(uuid.uuid4()), "user_me", "me@example.com", None, "member")
OTHER_ID = str(uuid.uuid4())


class FakeStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail = False

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise RuntimeError("s3 down")
        self.objects[key] = data

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def enqueue(self, document_id: str) -> None:
        self.sent.append(document_id)


class FakeVectors:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)


class FakeDocs:
    """In-memory stand-in for app.repos.documents."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.failed: dict[str, str] = {}

    async def find_duplicate(self, pool, sha256, scope, user_id):  # noqa: ANN001
        for r in self.rows.values():
            same_owner = scope == "enterprise" or r["owner_id"] == user_id
            if r["sha256"] == sha256 and r["scope"] == scope and same_owner:
                return r
        return None

    async def insert_document(self, pool, **kw):  # noqa: ANN001
        now = datetime.now(UTC)
        row = {
            "id": kw["doc_id"], "scope": kw["scope"], "uploaded_by": kw["user_id"],
            "owner_id": kw["user_id"] if kw["scope"] == "personal" else None,
            "title": kw["title"], "filename": kw["filename"], "mime": kw["mime"],
            "size_bytes": kw["size_bytes"], "sha256": kw["sha256"], "s3_key": kw["s3_key"],
            "status": "UPLOADING", "error": None, "page_count": None, "chunk_count": None,
            "created_at": now, "updated_at": now,
        }
        self.rows[row["id"]] = row
        return row

    async def get_visible(self, pool, doc_id, user_id):  # noqa: ANN001
        r = self.rows.get(doc_id)
        if r and (r["scope"] == "enterprise" or r["owner_id"] == user_id):
            return r
        return None

    async def list_visible(self, pool, user_id):  # noqa: ANN001
        return [r for r in self.rows.values() if r["scope"] == "enterprise" or r["owner_id"] == user_id]

    async def delete_document(self, pool, doc_id):  # noqa: ANN001
        self.rows.pop(doc_id, None)

    async def mark_failed(self, pool, doc_id, error):  # noqa: ANN001
        self.failed[doc_id] = error

    async def get_visible_chunk(self, pool, doc_id, chunk_id, user_id):  # noqa: ANN001
        return None


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict:
    fake = FakeDocs()
    for name in ("find_duplicate", "insert_document", "get_visible", "list_visible",
                 "delete_document", "mark_failed", "get_visible_chunk"):
        monkeypatch.setattr(docs_repo, name, getattr(fake, name))
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = object()
    app.state.store = FakeStore()
    app.state.ingest_queue = FakeQueue()
    app.state.enterprise_store = FakeVectors()
    return {"client": TestClient(app), "docs": fake, "state": app.state}


def _upload(client: TestClient, name: str = "policy.txt", data: bytes = b"hello", scope: str = "personal"):  # noqa: ANN202, E501
    return client.post("/v1/documents", files={"file": (name, data, "text/plain")}, data={"scope": scope})


def test_upload_stores_and_enqueues(env: dict) -> None:
    resp = _upload(env["client"])
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["status"] == "UPLOADING" and body["title"] == "policy"
    assert "s3_key" not in body and "sha256" not in body
    assert env["state"].ingest_queue.sent == [body["id"]]
    assert list(env["state"].store.objects) == [f"personal/{body['id']}/original.txt"]


def test_duplicate_upload_is_409(env: dict) -> None:
    _upload(env["client"])
    resp = _upload(env["client"])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CONFLICT"


def test_unsupported_type_is_415(env: dict) -> None:
    resp = _upload(env["client"], name="tool.exe")
    assert resp.status_code == 415 and resp.json()["success"] is False


def test_empty_file_is_400(env: dict) -> None:
    assert _upload(env["client"], data=b"").status_code == 400


def test_oversize_is_413(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 1)
    resp = _upload(env["client"], data=b"x" * (1024 * 1024 + 1))
    assert resp.status_code == 413


def test_enterprise_upload_closed_requires_admin(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "enterprise_upload_open", False)
    assert _upload(env["client"], scope="enterprise").status_code == 403


def test_storage_failure_marks_failed_and_502(env: dict) -> None:
    env["state"].store.fail = True
    resp = _upload(env["client"])
    assert resp.status_code == 502
    assert len(env["docs"].failed) == 1


def test_other_users_personal_doc_is_404(env: dict) -> None:
    doc_id = str(uuid.uuid4())
    env["docs"].rows[doc_id] = {"id": doc_id, "scope": "personal", "owner_id": OTHER_ID,
                                "uploaded_by": OTHER_ID, "s3_key": "k", "sha256": "s"}
    assert env["client"].get(f"/v1/documents/{doc_id}").status_code == 404
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 404


def test_enterprise_doc_delete_by_non_uploader_is_403(env: dict) -> None:
    doc_id = str(uuid.uuid4())
    env["docs"].rows[doc_id] = {"id": doc_id, "scope": "enterprise", "owner_id": None,
                                "uploaded_by": OTHER_ID, "s3_key": "k", "sha256": "s"}
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 403


def test_delete_own_enterprise_doc_cleans_everything(env: dict) -> None:
    doc_id = _upload(env["client"], scope="enterprise").json()["data"]["id"]
    resp = env["client"].delete(f"/v1/documents/{doc_id}")
    assert resp.status_code == 200
    assert env["state"].enterprise_store.deleted == [doc_id]
    assert env["docs"].rows == {} and env["state"].store.objects == {}


def test_invalid_uuid_is_422_envelope(env: dict) -> None:
    resp = env["client"].get("/v1/documents/not-a-uuid")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_chunk_is_404(env: dict) -> None:
    resp = env["client"].get(f"/v1/documents/{uuid.uuid4()}/chunks/{uuid.uuid4()}")
    assert resp.status_code == 404
