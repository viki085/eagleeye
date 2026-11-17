"""Document metadata access. Visibility rules mirror eagleeye_retrieval.access."""

import asyncpg

DOC_COLUMNS = """
    id, scope, owner_id, uploaded_by, title, filename, mime, size_bytes, status, error,
    page_count, chunk_count, created_at, updated_at
"""


def _visible(user_param: int) -> str:
    """Enterprise docs are visible to all users (Phase 2); personal docs to their owner."""
    return f"(scope = 'enterprise' OR owner_id = ${user_param}::uuid)"


async def insert_document(
    conn: asyncpg.Connection | asyncpg.Pool,
    *,
    doc_id: str,
    scope: str,
    user_id: str,
    title: str,
    filename: str,
    mime: str,
    size_bytes: int,
    sha256: str,
    s3_key: str,
) -> asyncpg.Record:
    return await conn.fetchrow(
        f"""
        INSERT INTO documents
            (id, scope, owner_id, uploaded_by, title, filename, mime, size_bytes, sha256, s3_key)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        RETURNING {DOC_COLUMNS}
        """,  # noqa: S608 - column list is a constant
        doc_id,
        scope,
        user_id if scope == "personal" else None,
        user_id,
        title,
        filename,
        mime,
        size_bytes,
        sha256,
        s3_key,
    )


async def find_duplicate(
    pool: asyncpg.Pool, sha256: str, scope: str, user_id: str
) -> asyncpg.Record | None:
    if scope == "enterprise":
        return await pool.fetchrow(
            "SELECT id, title FROM documents WHERE scope = 'enterprise' AND sha256 = $1", sha256
        )
    return await pool.fetchrow(
        """
        SELECT id, title FROM documents
        WHERE scope = 'personal' AND sha256 = $1 AND owner_id = $2::uuid
        """,
        sha256,
        user_id,
    )


async def list_visible(pool: asyncpg.Pool, user_id: str, limit: int = 2000) -> list[asyncpg.Record]:
    return await pool.fetch(
        f"""
        SELECT {DOC_COLUMNS} FROM documents
        WHERE {_visible(1)}
        ORDER BY created_at DESC LIMIT $2
        """,  # noqa: S608 - constants only
        user_id,
        limit,
    )


async def get_visible(pool: asyncpg.Pool, doc_id: str, user_id: str) -> asyncpg.Record | None:
    return await pool.fetchrow(
        f"SELECT {DOC_COLUMNS}, s3_key FROM documents WHERE id = $1 AND {_visible(2)}",  # noqa: S608
        doc_id,
        user_id,
    )


async def mark_failed(pool: asyncpg.Pool, doc_id: str, error: str) -> None:
    await pool.execute(
        "UPDATE documents SET status = 'FAILED', error = $2, updated_at = now() WHERE id = $1",
        doc_id,
        error,
    )


async def delete_document(pool: asyncpg.Pool, doc_id: str) -> None:
    await pool.execute("DELETE FROM documents WHERE id = $1", doc_id)


async def count_ready_visible(pool: asyncpg.Pool, user_id: str) -> int:
    count = await pool.fetchval(
        f"SELECT count(*) FROM documents WHERE status = 'READY' AND {_visible(1)}",  # noqa: S608
        user_id,
    )
    return int(count)


async def filter_visible_ready(pool: asyncpg.Pool, doc_ids: list[str], user_id: str) -> set[str]:
    if not doc_ids:
        return set()
    rows = await pool.fetch(
        f"""
        SELECT id FROM documents
        WHERE id = ANY($1::uuid[]) AND status = 'READY' AND {_visible(2)}
        """,  # noqa: S608 - constants only
        doc_ids,
        user_id,
    )
    return {str(r["id"]) for r in rows}


async def get_visible_chunk(
    pool: asyncpg.Pool, doc_id: str, chunk_id: str, user_id: str
) -> asyncpg.Record | None:
    return await pool.fetchrow(
        """
        SELECT c.id, c.chunk_no, c.content, c.heading_path, c.page, c.element_type,
               d.id AS document_id, d.title
        FROM document_chunks c JOIN documents d ON d.id = c.document_id
        WHERE c.id = $1 AND d.id = $2 AND d.status = 'READY'
          AND (c.scope = 'enterprise' OR (c.scope = 'personal' AND c.owner_id = $3::uuid))
        """,
        chunk_id,
        doc_id,
        user_id,
    )


async def list_visible_chunks(
    pool: asyncpg.Pool, doc_id: str, user_id: str
) -> list[asyncpg.Record]:
    """All chunks of one READY document the user may see, in reading order (document viewer)."""
    return await pool.fetch(
        """
        SELECT c.chunk_no, c.content, c.heading_path, c.page
        FROM document_chunks c JOIN documents d ON d.id = c.document_id
        WHERE d.id = $1 AND d.status = 'READY'
          AND (c.scope = 'enterprise' OR (c.scope = 'personal' AND c.owner_id = $2::uuid))
        ORDER BY c.chunk_no
        """,
        doc_id,
        user_id,
    )
