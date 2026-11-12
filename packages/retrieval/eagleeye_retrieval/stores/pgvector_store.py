"""Personal-scope vectors in Supabase pgvector (document_chunks.embedding)."""

import asyncpg

from eagleeye_retrieval.types import AccessScope, VectorHit, VectorPoint


def to_vector_literal(vector: list[float]) -> str:
    """pgvector text form; avoids a client-side codec dependency."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


class PgVectorPersonalStore:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        await self._pool.executemany(
            "UPDATE document_chunks SET embedding = $2::vector WHERE id = $1::uuid",
            [(p.chunk_id, to_vector_literal(p.vector)) for p in points],
        )

    async def search(
        self, vector: list[float], scope: AccessScope, limit: int
    ) -> list[VectorHit]:
        doc_filter = "AND document_id = ANY($4::uuid[])" if scope.doc_ids else ""
        args: list[object] = [to_vector_literal(vector), scope.user_id, limit]
        if scope.doc_ids:
            args.append(list(scope.doc_ids))
        rows = await self._pool.fetch(
            f"""
            SELECT id, 1 - (embedding <=> $1::vector) AS score
            FROM document_chunks
            WHERE scope = 'personal' AND owner_id = $2::uuid
              AND embedding IS NOT NULL {doc_filter}
            ORDER BY embedding <=> $1::vector
            LIMIT $3
            """,  # noqa: S608 — doc_filter is a constant, values are bound
            *args,
        )
        return [VectorHit(chunk_id=str(r["id"]), score=float(r["score"])) for r in rows]

    async def delete_document(self, document_id: str) -> None:
        """Embeddings live on chunk rows, which cascade with the document."""
        return None
