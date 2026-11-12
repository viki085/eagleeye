"""Retriever: rewrite → (vector ∥ vector ∥ keyword) per query → RRF → hydrate (C4 §4)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

import asyncpg
from eagleeye_llm.embeddings import Embedder
from eagleeye_llm.gateway import ChatMessage, LLMGateway

from eagleeye_retrieval import access
from eagleeye_retrieval.keyword_search import keyword_search
from eagleeye_retrieval.rewrite import rewrite_query
from eagleeye_retrieval.rrf import fuse
from eagleeye_retrieval.stores.base import VectorStore
from eagleeye_retrieval.types import AccessScope, RetrievalResult, VectorHit

logger = logging.getLogger(__name__)

VECTOR_TOP_N = 20
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3

KeywordFn = Callable[[str, AccessScope], Awaitable[list[str]]]
HydrateFn = Callable[[list[tuple[str, float]], AccessScope], Awaitable[list]]


def merge_vector_hits(*hit_lists: list[VectorHit], limit: int = VECTOR_TOP_N) -> list[VectorHit]:
    """Both stores use cosine similarity, so their scores are directly comparable."""
    best: dict[str, VectorHit] = {}
    for hits in hit_lists:
        for h in hits:
            if h.chunk_id not in best or h.score > best[h.chunk_id].score:
                best[h.chunk_id] = h
    return sorted(best.values(), key=lambda h: -h.score)[:limit]


class Retriever:
    def __init__(
        self,
        pool: asyncpg.Pool,
        llm: LLMGateway,
        embedder: Embedder,
        enterprise_store: VectorStore,
        personal_store: VectorStore,
        top_k: int = 5,
        min_score: float = 0.25,
        keyword_fn: KeywordFn | None = None,
        hydrate_fn: HydrateFn | None = None,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._stores = (enterprise_store, personal_store)
        self._top_k = top_k
        self._min_score = min_score
        self._keyword = keyword_fn or (lambda q, s: keyword_search(pool, q, s))
        self._hydrate = hydrate_fn or (lambda scored, s: access.hydrate(pool, scored, s))

    async def retrieve(
        self, question: str, history: list[ChatMessage], scope: AccessScope
    ) -> RetrievalResult:
        queries = await rewrite_query(self._llm, question, history)
        vectors = await self._embedder.embed(queries)
        per_query = await asyncio.gather(
            *(self._search_one(q, v, scope) for q, v in zip(queries, vectors, strict=True))
        )

        fused_rankings = [ranking for ranking, _ in per_query]
        best_score = max((score for _, score in per_query), default=0.0)
        final = fuse(fused_rankings)[: self._top_k]
        chunks = await self._hydrate(final, scope)
        low = not chunks or best_score < self._min_score
        logger.info(
            "retrieval: %d queries, %d chunks, best cosine %.3f, low_relevance=%s",
            len(queries), len(chunks), best_score, low,
        )
        return RetrievalResult(
            chunks=tuple(chunks), low_relevance=low, queries=tuple(queries), best_score=best_score
        )

    async def _search_one(
        self, query: str, vector: list[float], scope: AccessScope
    ) -> tuple[list[str], float]:
        """Returns (fused ranking of chunk ids for this query, best vector cosine)."""
        enterprise, personal, keyword = await asyncio.gather(
            self._safe_vector(self._stores[0], vector, scope),
            self._safe_vector(self._stores[1], vector, scope),
            self._safe_keyword(query, scope),
        )
        vector_hits = merge_vector_hits(enterprise, personal)
        best = vector_hits[0].score if vector_hits else 0.0
        fused = fuse(
            [[h.chunk_id for h in vector_hits], keyword],
            weights=[VECTOR_WEIGHT, KEYWORD_WEIGHT],
        )
        return [cid for cid, _ in fused], best

    async def _safe_vector(
        self, store: VectorStore, vector: list[float], scope: AccessScope
    ) -> list[VectorHit]:
        """One store being down degrades recall; it must not fail the whole answer."""
        try:
            return await store.search(vector, scope, VECTOR_TOP_N)
        except Exception:
            logger.warning("vector search failed on %s", type(store).__name__, exc_info=True)
            return []

    async def _safe_keyword(self, query: str, scope: AccessScope) -> list[str]:
        try:
            return await self._keyword(query, scope)
        except Exception:
            logger.warning("keyword search failed", exc_info=True)
            return []
