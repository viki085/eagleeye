"""Access-leak test against the real local Postgres (rolled back): a user's personal documents
never reach another user through any retrieval or listing path; enterprise ones reach both."""

import json
import uuid

import asyncpg
import pytest
from app.repos import documents as docs_repo
from eagleeye_core.config import get_settings
from eagleeye_retrieval.access import hydrate
from eagleeye_retrieval.keyword_search import keyword_search
from eagleeye_retrieval.stores.pgvector_store import PgVectorPersonalStore
from eagleeye_retrieval.types import AccessScope

pytestmark = pytest.mark.integration
DIM = 1536
MARKER_WORD = "zanzibarquokka"  # unique, so only the planted chunks can match


@pytest.fixture
async def conn():  # noqa: ANN201
    try:
        c = await asyncpg.connect(get_settings().database_url, timeout=3)
    except Exception:
        pytest.skip("local Postgres not available")
    await c.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")
    tx = c.transaction()
    await tx.start()
    try:
        yield c
    finally:
        await tx.rollback()
        await c.close()


def _vector(seed: float) -> str:
    return "[" + ",".join(f"{seed if i == 0 else 0.0:.3f}" for i in range(DIM)) + "]"


async def _user(c: asyncpg.Connection, name: str) -> str:
    return str(
        await c.fetchval(
            "INSERT INTO users (clerk_user_id, email) VALUES ($1, $2) RETURNING id",
            f"ck_{name}_{uuid.uuid4().hex[:6]}",
            f"{name}-{uuid.uuid4().hex[:6]}@leak.test",
        )
    )


async def _doc(
    c: asyncpg.Connection, scope: str, uploader: str, owner: str | None
) -> tuple[str, str]:
    doc = await c.fetchval(
        """
        INSERT INTO documents (scope, owner_id, uploaded_by, title, filename, mime, size_bytes,
                               sha256, s3_key, status)
        VALUES ($1, $2, $3, $4, 'f.txt', 'text/plain', 10, $5, 'k', 'READY') RETURNING id
        """,
        scope,
        owner,
        uploader,
        f"{scope} doc",
        uuid.uuid4().hex,
    )
    chunk = await c.fetchval(
        """
        INSERT INTO document_chunks (document_id, chunk_no, content, scope, owner_id,
                                     chunk_hash, embedding)
        VALUES ($1, 0, $2, $3, $4, 'h', $5::vector) RETURNING id
        """,
        doc,
        f"The {scope} plan mentions {MARKER_WORD} twice: {MARKER_WORD}.",
        scope,
        owner,
        _vector(1.0) if scope == "personal" else None,
    )
    return str(doc), str(chunk)


async def test_personal_documents_never_leak_to_other_users(conn: asyncpg.Connection) -> None:
    alice, bob = await _user(conn, "alice"), await _user(conn, "bob")
    a_doc, a_chunk = await _doc(conn, "personal", alice, alice)
    e_doc, e_chunk = await _doc(conn, "enterprise", alice, None)
    alice_scope, bob_scope = AccessScope(user_id=alice), AccessScope(user_id=bob)

    # keyword search
    assert set(await keyword_search(conn, MARKER_WORD, alice_scope)) >= {a_chunk, e_chunk}
    bob_hits = await keyword_search(conn, MARKER_WORD, bob_scope)
    assert a_chunk not in bob_hits and e_chunk in bob_hits

    # personal vector search
    store = PgVectorPersonalStore(conn)
    assert a_chunk in {
        h.chunk_id for h in await store.search([1.0] + [0.0] * (DIM - 1), alice_scope, 5)
    }
    assert a_chunk not in {
        h.chunk_id for h in await store.search([1.0] + [0.0] * (DIM - 1), bob_scope, 5)
    }

    # hydration re-applies access: even if a store returned Alice's chunk id for Bob, it's dropped
    hydrated = await hydrate(conn, [(a_chunk, 0.9), (e_chunk, 0.8)], bob_scope)
    assert [c.chunk_id for c in hydrated] == [e_chunk]

    # Bob even naming Alice's document explicitly (doc_ids filter) gets nothing from it
    pinned = AccessScope(user_id=bob, doc_ids=(a_doc,))
    assert await keyword_search(conn, MARKER_WORD, pinned) == []

    # listing, opening a document, opening a source passage
    bob_list = {str(r["id"]) for r in await docs_repo.list_visible(conn, bob)}
    assert a_doc not in bob_list and e_doc in bob_list
    assert await docs_repo.get_visible(conn, a_doc, bob) is None
    assert await docs_repo.get_visible_chunk(conn, a_doc, a_chunk, bob) is None
    assert await docs_repo.get_visible_chunk(conn, e_doc, e_chunk, bob) is not None
    assert await docs_repo.get_visible(conn, a_doc, alice) is not None


async def test_documents_that_are_not_ready_are_never_retrieved(conn: asyncpg.Connection) -> None:
    alice = await _user(conn, "alice")
    doc, chunk = await _doc(conn, "personal", alice, alice)
    await conn.execute("UPDATE documents SET status = 'EMBEDDING' WHERE id = $1", doc)
    assert chunk not in await keyword_search(conn, MARKER_WORD, AccessScope(user_id=alice))
    assert await hydrate(conn, [(chunk, 0.9)], AccessScope(user_id=alice)) == []
