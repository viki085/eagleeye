from typing import Protocol

from eagleeye_retrieval.types import AccessScope, VectorHit, VectorPoint


class VectorStore(Protocol):
    """One scope's vector index. Implementations must apply the scope filter in-query."""

    async def upsert(self, points: list[VectorPoint]) -> None: ...

    async def search(
        self, vector: list[float], scope: AccessScope, limit: int
    ) -> list[VectorHit]: ...

    async def delete_document(self, document_id: str) -> None: ...
