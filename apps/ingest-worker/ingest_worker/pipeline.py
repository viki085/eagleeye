"""Ingest pipeline: SCANNING → PARSING → CHUNKING → EMBEDDING → upsert → READY (C4 §3)."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import asyncpg
from eagleeye_core.config import get_settings
from eagleeye_core.storage import ObjectNotFoundError, ObjectStore, build_object_store
from eagleeye_llm.embeddings import Embedder, LiteLLMEmbedder
from eagleeye_retrieval.stores.base import VectorStore
from eagleeye_retrieval.stores.qdrant_store import QdrantEnterpriseStore, build_qdrant_client
from eagleeye_retrieval.types import VectorPoint

from ingest_worker import repo
from ingest_worker.chunking import PATH_SEP, Chunk, chunk
from ingest_worker.errors import PermanentIngestError, TransientIngestError
from ingest_worker.parsing.base import ParsedDocument, sanitize
from ingest_worker.parsing.registry import parser_for
from ingest_worker.sniff import sniff

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineDeps:
    conn: asyncpg.Connection
    store: ObjectStore
    embedder: Embedder
    enterprise_store: VectorStore


def embedding_text(title: str, c: Chunk) -> str:
    """Contextual chunk header: the stored content stays raw."""
    header = PATH_SEP.join(c.heading_path)
    return f"{title}\n{header}\n\n{c.content}" if header else f"{title}\n\n{c.content}"


async def _load_bytes(deps: PipelineDeps, s3_key: str) -> bytes:
    try:
        return await deps.store.get(s3_key)
    except ObjectNotFoundError as exc:
        raise PermanentIngestError("The uploaded file is missing from storage.") from exc
    except Exception as exc:
        raise TransientIngestError("Storage is temporarily unavailable.") from exc


async def _embed(deps: PipelineDeps, title: str, chunks: list[Chunk]) -> list[list[float]]:
    try:
        return await deps.embedder.embed([embedding_text(title, c) for c in chunks])
    except ValueError as exc:  # dimension mismatch = configuration error
        raise PermanentIngestError("Embedding configuration error; contact an admin.") from exc
    except Exception as exc:
        raise TransientIngestError("The embedding provider is temporarily unavailable.") from exc


async def _upsert(
    deps: PipelineDeps, doc: asyncpg.Record, chunks: list[Chunk], vectors: list[list[float]]
) -> None:
    doc_id = str(doc["id"])
    personal = doc["scope"] == "personal"
    try:
        async with deps.conn.transaction():
            ids = await repo.replace_chunks(deps.conn, doc, chunks, vectors if personal else None)
    except asyncpg.DataError as exc:  # bad data never succeeds on retry
        logger.warning("document %s: chunks rejected by the database: %s", doc["id"], exc)
        raise PermanentIngestError("The document contains text that can't be stored.") from exc
    if personal:
        return
    points = [
        VectorPoint(chunk_id=cid, document_id=doc_id, chunk_no=c.chunk_no, vector=v)
        for cid, c, v in zip(ids, chunks, vectors, strict=True)
    ]
    try:
        await deps.enterprise_store.delete_document(doc_id)
        await deps.enterprise_store.upsert(points)
    except Exception as exc:
        raise TransientIngestError("The vector store is temporarily unavailable.") from exc


def _chunks(parsed: ParsedDocument) -> list[Chunk]:
    s = get_settings()
    chunks = chunk(
        parsed.elements,
        max_chars=s.chunk_max_chars,
        soft_chars=s.chunk_soft_chars,
        min_chars=s.chunk_min_chars,
        overlap=s.chunk_overlap_chars,
    )
    if not chunks:
        raise PermanentIngestError("No text could be extracted from the document.")
    return chunks


async def reindex(document_id: str, deps: PipelineDeps) -> bool:
    """Re-chunk and re-embed a READY document with the current settings.

    The document stays READY throughout (retrieval only searches READY documents) and its
    chunks are swapped in one transaction. A permanent error keeps the old chunks rather than
    marking a working document FAILED. Transient errors raise, so the task retries.
    Returns True when the chunks were replaced.
    """
    doc = await repo.get_document(deps.conn, document_id)
    if doc is None or doc["status"] != "READY":
        logger.info("reindex %s skipped: not READY", document_id)
        return False
    try:
        data = await _load_bytes(deps, doc["s3_key"])
        parsed = sanitize(parser_for(sniff(doc["filename"], data)).parse(data))
        chunks = _chunks(parsed)
        vectors = await _embed(deps, doc["title"], chunks)
        await _upsert(deps, doc, chunks, vectors)
        await repo.mark_ready(deps.conn, document_id, len(chunks))
    except PermanentIngestError as exc:
        logger.warning("reindex %s skipped, old chunks kept: %s", document_id, exc.user_message)
        return False
    logger.info("document %s re-indexed with %d chunks", document_id, len(chunks))
    return True


async def process(document_id: str, deps: PipelineDeps) -> None:
    """Runs every stage. Permanent errors mark the document FAILED; transient ones raise."""
    doc = await repo.get_document(deps.conn, document_id)
    if doc is None:
        logger.info("document %s no longer exists; skipping", document_id)
        return
    try:
        await repo.set_status(deps.conn, document_id, "SCANNING")
        data = await _load_bytes(deps, doc["s3_key"])
        kind = sniff(doc["filename"], data)

        await repo.set_status(deps.conn, document_id, "PARSING")
        parsed = sanitize(parser_for(kind).parse(data))
        await repo.set_page_count(deps.conn, document_id, parsed.page_count)

        await repo.set_status(deps.conn, document_id, "CHUNKING")
        chunks = _chunks(parsed)

        await repo.set_status(deps.conn, document_id, "EMBEDDING")
        vectors = await _embed(deps, doc["title"], chunks)
        await _upsert(deps, doc, chunks, vectors)
        await repo.mark_ready(deps.conn, document_id, len(chunks))
        logger.info("document %s READY with %d chunks", document_id, len(chunks))
    except PermanentIngestError as exc:
        logger.warning("document %s failed permanently: %s", document_id, exc.user_message)
        await repo.set_status(deps.conn, document_id, "FAILED", exc.user_message)


async def mark_failed(document_id: str, message: str) -> None:
    conn = await repo.connect(get_settings().database_url)
    try:
        await repo.set_status(conn, document_id, "FAILED", message)
    finally:
        await conn.close()


async def _with_deps(
    document_id: str, step: Callable[[str, PipelineDeps], Awaitable[object]]
) -> None:
    """Builds and tears down every client inside one event loop (one Celery task)."""
    s = get_settings()
    conn = await repo.connect(s.database_url)
    qdrant = build_qdrant_client(s)
    try:
        enterprise = QdrantEnterpriseStore(qdrant, s.qdrant_collection, s.embed_dim)
        deps = PipelineDeps(
            conn=conn,
            store=build_object_store(),
            embedder=LiteLLMEmbedder(s.embed_model, s.embed_dim),
            enterprise_store=enterprise,
        )
        await enterprise.ensure_collection()
        await step(document_id, deps)
    finally:
        await qdrant.close()
        await conn.close()


async def run_pipeline(document_id: str) -> None:
    await _with_deps(document_id, process)


async def run_reindex(document_id: str) -> None:
    await _with_deps(document_id, reindex)
