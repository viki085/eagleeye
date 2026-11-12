"""The single authorization predicate for chunks (enforced below the LLM).

Enterprise chunks: visible to every signed-in user (Phase 2; groups/ACL deferred).
Personal chunks: owner only. Only READY documents are ever retrievable.
"""

import asyncpg

from eagleeye_retrieval.types import AccessScope, RetrievedChunk

MAX_CHUNK_CHARS = 2000
TRUNCATION_MARKER = " …[truncated]"


def access_predicate(first_param: int, scope: AccessScope) -> str:
    """SQL over aliases `c` (document_chunks) and `d` (documents).

    Parameters are numbered from `first_param` in the order `access_args` returns them.
    """
    n = first_param
    sql = (
        "d.status = 'READY' AND (c.scope = 'enterprise' "
        f"OR (c.scope = 'personal' AND c.owner_id = ${n}::uuid))"
    )
    if scope.doc_ids:
        n += 1
        sql += f" AND c.document_id = ANY(${n}::uuid[])"
    if scope.restricts_scope:
        n += 1
        sql += f" AND c.scope = ANY(${n}::text[])"
    return sql


def access_args(scope: AccessScope) -> list[object]:
    args: list[object] = [scope.user_id]
    if scope.doc_ids:
        args.append(list(scope.doc_ids))
    if scope.restricts_scope:
        args.append(list(scope.scopes))
    return args


def truncate(text: str, limit: int = MAX_CHUNK_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + TRUNCATION_MARKER


async def hydrate(
    pool: asyncpg.Pool, scored: list[tuple[str, float]], scope: AccessScope
) -> list[RetrievedChunk]:
    """Load chunk text for the fused ids, re-applying the access predicate.

    Anything a vector store returned that this user may not see is dropped here.
    """
    if not scored:
        return []
    ids = [cid for cid, _ in scored]
    rows = await pool.fetch(
        f"""
        SELECT c.id, c.document_id, d.title, c.scope, c.chunk_no, c.page,
               c.heading_path, c.content
        FROM document_chunks c JOIN documents d ON d.id = c.document_id
        WHERE c.id = ANY($1::uuid[]) AND {access_predicate(2, scope)}
        """,  # noqa: S608 — predicate is built from constants, values are bound
        ids,
        *access_args(scope),
    )
    by_id = {str(r["id"]): r for r in rows}
    chunks: list[RetrievedChunk] = []
    for cid, score in scored:
        row = by_id.get(cid)
        if row is None:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                document_id=str(row["document_id"]),
                title=row["title"],
                scope=row["scope"],
                chunk_no=row["chunk_no"],
                page=row["page"],
                heading_path=tuple(row["heading_path"] or ()),
                content=truncate(row["content"]),
                score=score,
            )
        )
    return chunks
