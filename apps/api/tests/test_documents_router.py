import uuid
from datetime import UTC, datetime

import pytest
from app.auth import AuthedUser, get_current_user
from app.main import create_app
from app.repos import admin_metrics
from app.repos import documents as docs_repo
from fastapi.testclient import TestClient

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

    async def get(self, key: str) -> bytes:
        from eagleeye_core.storage import ObjectNotFoundError

        if key not in self.objects:
            raise ObjectNotFoundError(key)
        return self.objects[key]


class FakeQueue:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def enqueue_ingest(self, document_id: str) -> None:
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
            "id": kw["doc_id"],
            "scope": kw["scope"],
            "uploaded_by": kw["user_id"],
            "owner_id": kw["user_id"] if kw["scope"] == "personal" else None,
            "title": kw["title"],
            "filename": kw["filename"],
            "mime": kw["mime"],
            "size_bytes": kw["size_bytes"],
            "sha256": kw["sha256"],
            "s3_key": kw["s3_key"],
            "status": "UPLOADING",
            "error": None,
            "page_count": None,
            "chunk_count": None,
            "created_at": now,
            "updated_at": now,
        }
        self.rows[row["id"]] = row
        return row

    async def get_visible(self, pool, doc_id, user_id):  # noqa: ANN001
        r = self.rows.get(doc_id)
        if r and (r["scope"] == "enterprise" or r["owner_id"] == user_id):
            return r
        return None

    async def list_visible(self, pool, user_id):  # noqa: ANN001
        return [
            r for r in self.rows.values() if r["scope"] == "enterprise" or r["owner_id"] == user_id
        ]

    async def delete_document(self, pool, doc_id):  # noqa: ANN001
        self.rows.pop(doc_id, None)

    async def mark_failed(self, pool, doc_id, error):  # noqa: ANN001
        self.failed[doc_id] = error

    chunk: dict | None = None
    figures: list[str] = []

    async def get_visible_chunk(self, pool, doc_id, chunk_id, user_id):  # noqa: ANN001
        return self.chunk

    async def figure_keys(self, pool, doc_id):  # noqa: ANN001
        return list(self.figures)

    async def list_visible_chunks(self, pool, doc_id, user_id):  # noqa: ANN001
        if self.rows.get(doc_id, {}).get("status") != "READY":
            return []
        return [
            {"chunk_no": 1, "content": "Second part", "heading_path": ["B"], "page": 2},
            {"chunk_no": 0, "content": "First part", "heading_path": ["A"], "page": 1},
        ][::-1]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> dict:
    fake = FakeDocs()
    for name in (
        "find_duplicate",
        "insert_document",
        "get_visible",
        "list_visible",
        "delete_document",
        "mark_failed",
        "get_visible_chunk",
        "list_visible_chunks",
        "figure_keys",
    ):
        monkeypatch.setattr(docs_repo, name, getattr(fake, name))
    audit: list[tuple[str, str, dict]] = []

    async def record(pool, user_id, category, detail):  # noqa: ANN001, ANN202
        if getattr(record, "fail", False):
            raise RuntimeError("audit down")
        audit.append((user_id, category, detail))

    monkeypatch.setattr(admin_metrics, "record_admin_action", record)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: ME
    app.state.pool = object()
    app.state.store = FakeStore()
    app.state.task_queue = FakeQueue()
    app.state.enterprise_store = FakeVectors()
    return {
        "client": TestClient(app),
        "docs": fake,
        "state": app.state,
        "audit": audit,
        "record": record,
    }


def _upload(
    client: TestClient, name: str = "policy.txt", data: bytes = b"hello", scope: str = "personal"
):  # noqa: ANN202, E501
    return client.post(
        "/v1/documents", files={"file": (name, data, "text/plain")}, data={"scope": scope}
    )


def test_upload_stores_and_enqueues(env: dict) -> None:
    resp = _upload(env["client"])
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["status"] == "UPLOADING" and body["title"] == "policy"
    assert "s3_key" not in body and "sha256" not in body
    assert env["state"].task_queue.sent == [body["id"]]
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


def test_member_cannot_upload_enterprise_by_default(env: dict) -> None:
    resp = _upload(env["client"], scope="enterprise")
    assert resp.status_code == 403 and "knowledge admins" in resp.json()["error"]["message"]
    assert env["docs"].rows == {} and env["state"].store.objects == {}


def test_open_override_lets_members_upload_enterprise(
    env: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from eagleeye_core.config import get_settings

    monkeypatch.setattr(get_settings(), "enterprise_upload_open", True)
    assert _upload(env["client"], scope="enterprise").status_code == 201


def _as(env: dict, role: str) -> None:
    env["client"].app.dependency_overrides[get_current_user] = lambda: AuthedUser(
        ME.id, ME.clerk_user_id, ME.email, ME.display_name, role
    )


def test_me_reports_enterprise_permission(env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_row(pool, user_id):  # noqa: ANN001, ANN202 - fall back to the request's user
        return None

    monkeypatch.setattr("app.routers.me.fresh_role", no_row)
    assert env["client"].get("/v1/me").json()["data"]["can_manage_enterprise"] is False
    _as(env, "knowledge_admin")
    assert env["client"].get("/v1/me").json()["data"]["can_manage_enterprise"] is True


def test_storage_failure_marks_failed_and_502(env: dict) -> None:
    env["state"].store.fail = True
    resp = _upload(env["client"])
    assert resp.status_code == 502
    assert len(env["docs"].failed) == 1


def test_other_users_personal_doc_is_404(env: dict) -> None:
    doc_id = str(uuid.uuid4())
    env["docs"].rows[doc_id] = {
        "id": doc_id,
        "scope": "personal",
        "owner_id": OTHER_ID,
        "uploaded_by": OTHER_ID,
        "s3_key": "k",
        "sha256": "s",
    }
    assert env["client"].get(f"/v1/documents/{doc_id}").status_code == 404
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 404


@pytest.mark.parametrize("uploaded_by", [OTHER_ID, ME.id])
def test_member_cannot_delete_enterprise_docs_even_their_own(env: dict, uploaded_by: str) -> None:
    doc_id = str(uuid.uuid4())
    env["docs"].rows[doc_id] = {
        "id": doc_id,
        "scope": "enterprise",
        "owner_id": None,
        "uploaded_by": uploaded_by,
        "s3_key": "k",
        "sha256": "s",
    }
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 403
    assert doc_id in env["docs"].rows


def test_knowledge_admin_manages_enterprise_docs(env: dict) -> None:
    _as(env, "knowledge_admin")
    doc_id = _upload(env["client"], scope="enterprise").json()["data"]["id"]
    resp = env["client"].delete(f"/v1/documents/{doc_id}")
    assert resp.status_code == 200
    assert env["state"].enterprise_store.deleted == [doc_id]
    assert env["docs"].rows == {} and env["state"].store.objects == {}


def test_enterprise_add_and_delete_are_audited(env: dict) -> None:
    _as(env, "admin")
    _upload(env["client"])  # personal: not an admin action
    doc_id = _upload(env["client"], name="handbook.txt", data=b"hb", scope="enterprise").json()[
        "data"
    ]["id"]
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 200
    assert [(c, d["title"]) for _, c, d in env["audit"]] == [
        ("enterprise_doc_added", "handbook"),
        ("enterprise_doc_deleted", "handbook"),
    ]


def test_enterprise_delete_is_refused_when_audit_fails(env: dict) -> None:
    _as(env, "admin")
    doc_id = _upload(env["client"], scope="enterprise").json()["data"]["id"]
    env["record"].fail = True
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 500
    assert doc_id in env["docs"].rows and env["state"].enterprise_store.deleted == []


def test_invalid_uuid_is_422_envelope(env: dict) -> None:
    resp = env["client"].get("/v1/documents/not-a-uuid")
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_missing_chunk_is_404(env: dict) -> None:
    resp = env["client"].get(f"/v1/documents/{uuid.uuid4()}/chunks/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_a_table_chunk_says_it_is_a_table(env: dict) -> None:
    doc_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    env["docs"].chunk = {
        "id": chunk_id,
        "chunk_no": 3,
        "content": "| Region | 2025 |\n| --- | --- |\n| North | 150 |",
        "heading_path": ["Revenue"],
        "page": 2,
        "element_type": "table",
        "document_id": doc_id,
        "title": "Report",
    }
    resp = env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["element_type"] == "table" and data["content"].startswith("| Region")


def _stored_doc(env: dict, *, scope: str, owner: str | None, mime: str, data: bytes) -> str:
    doc_id = str(uuid.uuid4())
    key = f"{scope}/{doc_id}/original"
    env["state"].store.objects[key] = data
    env["docs"].rows[doc_id] = {
        "id": doc_id,
        "scope": scope,
        "owner_id": owner,
        "uploaded_by": owner or OTHER_ID,
        "s3_key": key,
        "sha256": "s",
        "mime": mime,
        "filename": 'Policy "v2".pdf',
        "status": "READY",
    }
    return doc_id


def test_file_is_served_inline_to_anyone_who_can_see_it(env: dict) -> None:
    doc_id = _stored_doc(
        env, scope="enterprise", owner=None, mime="application/pdf", data=b"%PDF-1"
    )
    resp = env["client"].get(f"/v1/documents/{doc_id}/file")
    assert resp.status_code == 200 and resp.content == b"%PDF-1"
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.headers["content-disposition"] == 'inline; filename="Policy v2.pdf"'
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_file_of_another_users_personal_doc_is_404(env: dict) -> None:
    doc_id = _stored_doc(env, scope="personal", owner=OTHER_ID, mime="text/plain", data=b"secret")
    assert env["client"].get(f"/v1/documents/{doc_id}/file").status_code == 404
    assert env["client"].get(f"/v1/documents/{doc_id}/text").status_code == 404


def test_unviewable_types_are_sent_as_opaque_bytes(env: dict) -> None:
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    doc_id = _stored_doc(env, scope="personal", owner=ME.id, mime=docx, data=b"PK")
    resp = env["client"].get(f"/v1/documents/{doc_id}/file")
    assert resp.headers["content-type"] == "application/octet-stream"


def test_missing_object_is_404(env: dict) -> None:
    doc_id = _stored_doc(env, scope="personal", owner=ME.id, mime="text/plain", data=b"x")
    env["state"].store.objects.clear()
    assert env["client"].get(f"/v1/documents/{doc_id}/file").status_code == 404


def test_text_returns_chunks_in_reading_order(env: dict) -> None:
    doc_id = _stored_doc(env, scope="enterprise", owner=None, mime="text/plain", data=b"x")
    body = env["client"].get(f"/v1/documents/{doc_id}/text").json()["data"]
    assert [c["content"] for c in body] == ["First part", "Second part"]
    assert body[0]["heading_path"] == ["A"] and body[1]["page"] == 2


def _figure_chunk(env: dict, asset_key: str | None) -> tuple[uuid.UUID, uuid.UUID]:
    doc_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    env["docs"].chunk = {
        "id": chunk_id,
        "chunk_no": 0,
        "content": "Line chart of LNG exports, 2023-2027.",
        "heading_path": [],
        "page": 1,
        "element_type": "image",
        "asset_key": asset_key,
        "document_id": doc_id,
        "title": "Deck",
    }
    return doc_id, chunk_id


def test_a_cited_figure_is_served_as_png_under_the_chunk_rule(env: dict) -> None:
    key = "personal/d1/figures/000.png"
    env["state"].store.objects[key] = b"\x89PNG fake"
    doc_id, chunk_id = _figure_chunk(env, key)
    data = env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}").json()["data"]
    assert data["has_image"] is True and data["element_type"] == "image"
    resp = env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}/image")
    assert resp.status_code == 200 and resp.content == b"\x89PNG fake"
    assert resp.headers["content-type"] == "image/png"
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_no_figure_or_an_invisible_chunk_is_404(env: dict) -> None:
    doc_id, chunk_id = _figure_chunk(env, None)
    assert env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}/image").status_code == 404
    env["docs"].chunk = None  # not visible to this user
    assert env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}/image").status_code == 404


def test_deleting_a_document_removes_its_figures(env: dict) -> None:
    doc_id = _upload(env["client"]).json()["data"]["id"]
    figure = f"personal/{doc_id}/figures/000.png"
    env["state"].store.objects[figure] = b"png"
    env["docs"].figures = [figure]
    assert env["client"].delete(f"/v1/documents/{doc_id}").status_code == 200
    assert env["state"].store.objects == {}


def test_a_cited_pdf_page_is_shown_with_its_passage(env: dict) -> None:
    from test_page_render import blank_pdf

    doc_id, chunk_id = _figure_chunk(env, None)
    env["state"].store.objects["enterprise/d/original.pdf"] = blank_pdf(1)
    env["docs"].chunk |= {
        "mime": "application/pdf",
        "s3_key": "enterprise/d/original.pdf",
        "bbox": [72.0, 700.0, 300.0, 650.0],
    }
    data = env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}").json()["data"]
    assert data["has_page"] is True
    resp = env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}/page")
    assert resp.status_code == 200 and resp.content.startswith(b"\x89PNG")
    assert resp.headers["x-content-type-options"] == "nosniff"


def test_page_is_404_for_non_pdfs_missing_pages_and_invisible_chunks(env: dict) -> None:
    from test_page_render import blank_pdf

    doc_id, chunk_id = _figure_chunk(env, None)
    url = f"/v1/documents/{doc_id}/chunks/{chunk_id}/page"
    env["docs"].chunk |= {"mime": "text/markdown", "s3_key": "k", "bbox": None}
    assert (
        env["client"].get(f"/v1/documents/{doc_id}/chunks/{chunk_id}").json()["data"]["has_page"]
        is False
    )
    assert env["client"].get(url).status_code == 404
    env["state"].store.objects["k"] = blank_pdf(1)
    env["docs"].chunk |= {"mime": "application/pdf", "page": 5}  # beyond the last page
    assert env["client"].get(url).status_code == 404
    env["docs"].chunk = None
    assert env["client"].get(url).status_code == 404
