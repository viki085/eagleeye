from eagleeye_llm.gateway import Usage
from eagleeye_retrieval.access import TRUNCATION_MARKER, truncate
from eagleeye_retrieval.service import Retriever, merge_vector_hits
from eagleeye_retrieval.types import AccessScope, RetrievedChunk, VectorHit


class _LLM:
    async def complete(self, tier, messages, max_tokens=1024):  # noqa: ANN001
        return '{"standalone": "q1", "variants": ["q2"]}', Usage()

    def stream(self, tier, messages, max_tokens=2048):  # noqa: ANN001
        raise NotImplementedError


class _Embedder:
    dim = 3

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3] for _ in texts]


class _Store:
    def __init__(self, hits: list[VectorHit] | Exception) -> None:
        self.hits = hits
        self.scopes: list[AccessScope] = []

    async def search(self, vector, scope, limit):  # noqa: ANN001
        self.scopes.append(scope)
        if isinstance(self.hits, Exception):
            raise self.hits
        return self.hits

    async def upsert(self, points):  # noqa: ANN001
        return None

    async def delete_document(self, document_id):  # noqa: ANN001
        return None


def _chunk(cid: str, score: float) -> RetrievedChunk:
    return RetrievedChunk(cid, "d1", "Doc", "personal", 0, 1, ("H",), "text", score)


def _make(
    enterprise: _Store,
    personal: _Store,
    keyword: list[str],
    allowed: set[str] | None = None,
    min_score: float = 0.25,
) -> Retriever:
    async def keyword_fn(q, s):  # noqa: ANN001
        return keyword

    async def hydrate_fn(scored, s):  # noqa: ANN001
        return [_chunk(c, sc) for c, sc in scored if allowed is None or c in allowed]

    return Retriever(
        pool=None,  # type: ignore[arg-type]
        llm=_LLM(),
        embedder=_Embedder(),
        enterprise_store=enterprise,
        personal_store=personal,
        top_k=3,
        min_score=min_score,
        keyword_fn=keyword_fn,
        hydrate_fn=hydrate_fn,
    )


def test_merge_vector_hits_keeps_best_score() -> None:
    merged = merge_vector_hits([VectorHit("a", 0.5), VectorHit("b", 0.9)], [VectorHit("a", 0.7)])
    assert [(h.chunk_id, h.score) for h in merged] == [("b", 0.9), ("a", 0.7)]


async def test_retrieve_fuses_both_stores_and_keyword() -> None:
    r = _make(_Store([VectorHit("e1", 0.8)]), _Store([VectorHit("p1", 0.6)]), ["k1", "e1"])
    result = await r.retrieve("question", [], AccessScope("u1"))
    ids = [c.chunk_id for c in result.chunks]
    assert ids[0] == "e1"  # in vector + keyword
    assert set(ids) == {"e1", "p1", "k1"}
    assert result.low_relevance is False
    assert result.queries == ("q1", "q2")
    assert result.best_score == 0.8


async def test_low_relevance_when_best_score_below_floor() -> None:
    r = _make(_Store([VectorHit("e1", 0.1)]), _Store([]), [], min_score=0.25)
    assert (await r.retrieve("q", [], AccessScope("u1"))).low_relevance is True


async def test_hydrate_drops_unauthorised_ids() -> None:
    r = _make(_Store([VectorHit("secret", 0.9)]), _Store([VectorHit("mine", 0.5)]), [], {"mine"})
    result = await r.retrieve("q", [], AccessScope("u1"))
    assert [c.chunk_id for c in result.chunks] == ["mine"]


async def test_store_failure_degrades_not_fails() -> None:
    r = _make(_Store(RuntimeError("qdrant down")), _Store([VectorHit("p1", 0.7)]), [])
    result = await r.retrieve("q", [], AccessScope("u1"))
    assert [c.chunk_id for c in result.chunks] == ["p1"]


async def test_scope_is_passed_to_stores() -> None:
    ent, per = _Store([]), _Store([])
    scope = AccessScope("u1", ("d1",))
    await _make(ent, per, []).retrieve("q", [], scope)
    assert ent.scopes[0] == scope and per.scopes[0] == scope


async def test_scope_restriction_skips_other_store() -> None:
    ent, per = _Store([VectorHit("e1", 0.9)]), _Store([VectorHit("p1", 0.8)])
    scope = AccessScope("u1", scopes=("personal",))
    result = await _make(ent, per, []).retrieve("q", [], scope)
    assert ent.scopes == [] and [c.chunk_id for c in result.chunks] == ["p1"]


async def test_rewrite_false_uses_query_verbatim() -> None:
    r = _make(_Store([VectorHit("e1", 0.9)]), _Store([]), [])
    result = await r.retrieve("exact supervisor query", [], AccessScope("u1"), rewrite=False)
    assert result.queries == ("exact supervisor query",)


def test_access_predicate_numbering() -> None:
    from eagleeye_retrieval.access import access_args, access_predicate

    scope = AccessScope("u1", doc_ids=("d1",), scopes=("enterprise",))
    sql = access_predicate(3, scope)
    assert "$3::uuid" in sql and "$4::uuid[]" in sql and "$5::text[]" in sql
    assert access_args(scope) == ["u1", ["d1"], ["enterprise"]]
    assert "text[]" not in access_predicate(2, AccessScope("u1"))


def test_truncate() -> None:
    assert truncate("short", 10) == "short"
    assert truncate("x" * 20, 10).endswith(TRUNCATION_MARKER)
