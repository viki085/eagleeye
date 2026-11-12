"""Enterprise-scope vectors in Qdrant (ADR-04). Point id == document_chunks.id."""

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from eagleeye_retrieval.types import AccessScope, VectorHit, VectorPoint

logger = logging.getLogger(__name__)

UPSERT_BATCH = 128


class CollectionDimMismatchError(RuntimeError):
    pass


class QdrantEnterpriseStore:
    def __init__(self, client: AsyncQdrantClient, collection: str, dim: int) -> None:
        self._client = client
        self._collection = collection
        self._dim = dim

    async def ensure_collection(self) -> None:
        if await self._client.collection_exists(self._collection):
            info = await self._client.get_collection(self._collection)
            vectors = info.config.params.vectors
            size = vectors.size if isinstance(vectors, qm.VectorParams) else None
            if size is not None and size != self._dim:
                raise CollectionDimMismatchError(
                    f"Qdrant collection {self._collection} has dim {size}, EMBED_DIM is "
                    f"{self._dim}; drop the collection or fix EMBED_DIM"
                )
            return
        logger.info("creating qdrant collection %s (dim=%d)", self._collection, self._dim)
        await self._client.create_collection(
            self._collection,
            vectors_config=qm.VectorParams(size=self._dim, distance=qm.Distance.COSINE),
        )
        await self._client.create_payload_index(
            self._collection, "document_id", field_schema=qm.PayloadSchemaType.KEYWORD
        )

    async def upsert(self, points: list[VectorPoint]) -> None:
        for start in range(0, len(points), UPSERT_BATCH):
            batch = points[start : start + UPSERT_BATCH]
            await self._client.upsert(
                self._collection,
                points=[
                    qm.PointStruct(
                        id=p.chunk_id,
                        vector=p.vector,
                        payload={"document_id": p.document_id, "chunk_no": p.chunk_no},
                    )
                    for p in batch
                ],
                wait=True,
            )

    async def search(
        self, vector: list[float], scope: AccessScope, limit: int
    ) -> list[VectorHit]:
        query_filter = None
        if scope.doc_ids:
            query_filter = qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="document_id", match=qm.MatchAny(any=list(scope.doc_ids))
                    )
                ]
            )
        resp = await self._client.query_points(
            self._collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=False,
        )
        return [VectorHit(chunk_id=str(p.id), score=float(p.score)) for p in resp.points]

    async def delete_document(self, document_id: str) -> None:
        await self._client.delete(
            self._collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id))
                    ]
                )
            ),
            wait=True,
        )
