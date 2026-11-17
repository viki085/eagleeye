"""Worker-side document/chunk persistence (parameterised SQL only)."""

import json

import asyncpg
from eagleeye_retrieval.stores.pgvector_store import to_vector_literal

from ingest_worker.chunking import Chunk

ALLOWED_STAGE_STATUSES = {"SCANNING", "PARSING", "CHUNKING", "EMBEDDING", "READY", "FAILED"}
MAX_ERROR_CHARS = 500


async def get_document(conn: asyncpg.Connection, document_id: str) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT id, scope, owner_id, title, filename, s3_key, status FROM documents WHERE id = $1",
        document_id,
    )


async def set_status(
    conn: asyncpg.Connection,
    document_id: str,
    status: str,
    error: str | None = None,
) -> None:
    if status not in ALLOWED_STAGE_STATUSES:
        raise ValueError(f"invalid status {status}")
    await conn.execute(
        "UPDATE documents SET status = $2, error = $3, updated_at = now() WHERE id = $1",
        document_id,
        status,
        error[:MAX_ERROR_CHARS] if error else None,
    )


async def set_page_count(conn: asyncpg.Connection, document_id: str, pages: int | None) -> None:
    await conn.execute("UPDATE documents SET page_count = $2 WHERE id = $1", document_id, pages)


async def set_parse_report(conn: asyncpg.Connection, document_id: str, report: dict) -> None:
    await conn.execute("UPDATE documents SET parse_report = $2 WHERE id = $1", document_id, report)


async def mark_ready(conn: asyncpg.Connection, document_id: str, chunk_count: int) -> None:
    await conn.execute(
        """
        UPDATE documents SET status = 'READY', error = NULL, chunk_count = $2, updated_at = now()
        WHERE id = $1
        """,
        document_id,
        chunk_count,
    )


async def replace_chunks(
    conn: asyncpg.Connection,
    doc: asyncpg.Record,
    chunks: list[Chunk],
    vectors: list[list[float]] | None,
) -> list[str]:
    """Idempotent: drop any previous chunks for the document, insert the new set.

    `vectors` is given for personal scope only (pgvector); enterprise vectors go to Qdrant.
    Caller wraps this in a transaction.
    """
    await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", doc["id"])
    ids: list[str] = []
    for i, c in enumerate(chunks):
        embedding = to_vector_literal(vectors[i]) if vectors is not None else None
        chunk_id = await conn.fetchval(
            """
            INSERT INTO document_chunks
                (document_id, chunk_no, content, heading_path, page, scope, owner_id,
                 chunk_hash, embedding, element_type, bbox, table_html)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector, $10, $11, $12)
            RETURNING id
            """,
            doc["id"],
            c.chunk_no,
            c.content,
            list(c.heading_path),
            c.page,
            doc["scope"],
            doc["owner_id"],
            c.chunk_hash,
            embedding,
            c.element_type,
            list(c.bbox) if c.bbox else None,
            c.table_html,
        )
        ids.append(str(chunk_id))
    return ids


async def connect(database_url: str) -> asyncpg.Connection:
    conn = await asyncpg.connect(database_url)
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    return conn
