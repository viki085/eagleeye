from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import pytest
from eagleeye_core.storage import ObjectNotFoundError
from ingest_worker import pipeline
from ingest_worker.chunking import Chunk
from ingest_worker.errors import TransientIngestError

DOC_ID = "00000000-0000-0000-0000-000000000001"
BODY = ("The refund window is thirty days. " * 30).encode()


class _Conn:
    @asynccontextmanager
    async def transaction(self):  # noqa: ANN201
        yield


class _Store:
    def __init__(self, data: bytes | Exception) -> None:
        self.data = data

    async def get(self, key: str) -> bytes:
        if isinstance(self.data, Exception):
            raise self.data
        return self.data


class _Embedder:
    dim = 3

    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.texts: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if self.fail:
            raise self.fail
        self.texts = texts
        return [[0.1, 0.2, 0.3] for _ in texts]


class _Vectors:
    def __init__(self) -> None:
        self.points: list = []
        self.deleted: list[str] = []

    async def upsert(self, points):  # noqa: ANN001
        self.points = points

    async def delete_document(self, document_id: str) -> None:
        self.deleted.append(document_id)

    async def search(self, *a):  # noqa: ANN002
        return []


@dataclass
class FakeRepo:
    scope: str = "enterprise"
    filename: str = "policy.txt"
    statuses: list[tuple[str, str | None]] = field(default_factory=list)
    vectors_passed: list | None = None

    async def get_document(self, conn, document_id):  # noqa: ANN001
        return {"id": DOC_ID, "scope": self.scope, "owner_id": None, "title": "Policy",
                "filename": self.filename, "s3_key": "k", "status": "UPLOADING"}

    async def set_status(self, conn, document_id, status, error=None):  # noqa: ANN001
        self.statuses.append((status, error))

    async def set_page_count(self, conn, document_id, pages):  # noqa: ANN001
        return None

    async def mark_ready(self, conn, document_id, n):  # noqa: ANN001
        self.statuses.append(("READY", None))

    async def replace_chunks(self, conn, doc, chunks: list[Chunk], vectors):  # noqa: ANN001
        self.vectors_passed = vectors
        return [f"c{i}" for i in range(len(chunks))]


@pytest.fixture
def fake_repo(monkeypatch: pytest.MonkeyPatch) -> FakeRepo:
    fake = FakeRepo()
    for name in ("get_document", "set_status", "set_page_count", "mark_ready", "replace_chunks"):
        monkeypatch.setattr(pipeline.repo, name, getattr(fake, name))
    return fake


def _deps(store: _Store, embedder: _Embedder, vectors: _Vectors) -> pipeline.PipelineDeps:
    return pipeline.PipelineDeps(_Conn(), store, embedder, vectors)  # type: ignore[arg-type]


async def test_enterprise_doc_goes_to_qdrant(fake_repo: FakeRepo) -> None:
    vectors, emb = _Vectors(), _Embedder()
    await pipeline.process(DOC_ID, _deps(_Store(BODY), emb, vectors))
    stages = [s for s, _ in fake_repo.statuses]
    assert stages == ["SCANNING", "PARSING", "CHUNKING", "EMBEDDING", "READY"]
    assert vectors.deleted == [DOC_ID] and len(vectors.points) >= 1
    assert fake_repo.vectors_passed is None
    assert emb.texts[0].startswith("Policy\n")


async def test_personal_doc_goes_to_pgvector(fake_repo: FakeRepo) -> None:
    fake_repo.scope = "personal"
    vectors = _Vectors()
    await pipeline.process(DOC_ID, _deps(_Store(BODY), _Embedder(), vectors))
    assert vectors.points == [] and fake_repo.vectors_passed is not None


async def test_spoofed_file_marks_failed(fake_repo: FakeRepo) -> None:
    fake_repo.filename = "policy.pdf"
    await pipeline.process(DOC_ID, _deps(_Store(BODY), _Embedder(), _Vectors()))
    status, error = fake_repo.statuses[-1]
    assert status == "FAILED" and "extension" in (error or "")


async def test_missing_object_marks_failed(fake_repo: FakeRepo) -> None:
    await pipeline.process(DOC_ID, _deps(_Store(ObjectNotFoundError("k")), _Embedder(), _Vectors()))
    assert fake_repo.statuses[-1][0] == "FAILED"


async def test_embedding_outage_is_transient(fake_repo: FakeRepo) -> None:
    with pytest.raises(TransientIngestError):
        await pipeline.process(
            DOC_ID, _deps(_Store(BODY), _Embedder(RuntimeError("503")), _Vectors())
        )
    assert fake_repo.statuses[-1][0] == "EMBEDDING"
