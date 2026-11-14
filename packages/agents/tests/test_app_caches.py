"""EagleEye's own cache: guard verdicts, query rewrites, query embeddings and whole answers."""

import json

import pytest
from eagleeye_agents import answer_cache, persistence, runner
from eagleeye_agents.context import AgentSettings
from eagleeye_agents.guard.classifier import classify
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_events.names import CITATION
from eagleeye_llm.embeddings import CachingEmbedder
from eagleeye_llm.gateway import ChatMessage
from eagleeye_retrieval.rewrite import rewrite_query
from eagleeye_retrieval.types import RetrievalResult
from fakes import FakeLLM, FakeRetriever, FakeSink, Turn, chunk, guard_json
from test_runner import DB, FakeRedis, db  # noqa: F401 - db is a fixture


class MemoryCache:
    """AppCache stand-in: same get/put contract, plus a record of what was looked up."""

    def __init__(self) -> None:
        self.data: dict[tuple[str, str], dict] = {}
        self.lookups: list[tuple[str, bool]] = []

    @staticmethod
    def _k(kind: str, parts) -> tuple[str, str]:  # noqa: ANN001
        return kind, json.dumps(list(parts), default=str)

    async def get(self, kind: str, parts) -> dict | None:  # noqa: ANN001
        value = self.data.get(self._k(kind, parts))
        self.lookups.append((kind, value is not None))
        return value

    async def put(self, kind: str, parts, value: dict) -> None:  # noqa: ANN001
        self.data[self._k(kind, parts)] = value


async def test_guard_verdict_is_reused_for_identical_input() -> None:
    cache, llm = MemoryCache(), FakeLLM([guard_json(intent="docs")])
    first, usage = await classify(llm, "sys", "What is the reefer SOP?", [], ["SOP"], False, cache)
    again, again_usage = await classify(
        llm, "sys", "What is the reefer SOP?", [], ["SOP"], False, cache
    )
    assert len(llm.complete_calls) == 1  # second verdict came from the cache
    assert first == again and again_usage.cost_usd == 0 and usage.cost_usd > 0
    await classify(llm, "sys", "Another question", [], ["SOP"], False, cache)
    assert len(llm.complete_calls) == 2  # different input, new call


async def test_query_rewrite_is_reused() -> None:
    cache = MemoryCache()
    llm = FakeLLM([json.dumps({"standalone": "reefer alarm rules", "variants": ["reefer SOP"]})])
    first = await rewrite_query(llm, "reefer alarms?", [], cache)
    again = await rewrite_query(llm, "reefer alarms?", [], cache)
    assert first == again == ["reefer alarm rules", "reefer SOP"]
    assert len(llm.complete_calls) == 1


class CountingEmbedder:
    dim = 3

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        return [[float(len(t)), 0.0, 1.0] for t in texts]


async def test_query_embeddings_are_reused_text_by_text() -> None:
    inner, cache = CountingEmbedder(), MemoryCache()
    embedder = CachingEmbedder(inner, cache, "embed-model")
    first = await embedder.embed(["a", "bb"])
    mixed = await embedder.embed(["bb", "ccc"])
    assert inner.calls == [["a", "bb"], ["ccc"]]  # only the new text was embedded
    assert mixed == [first[1], [3.0, 0.0, 1.0]]


def test_question_normalisation() -> None:
    assert answer_cache.normalise("  What is the Reefer SOP?? ") == "what is the reefer sop"


@pytest.fixture
def fixed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def key(pool, user_id, role, question, versions, models):  # noqa: ANN001, ANN202
        return (answer_cache.normalise(question), role)

    async def role(pool, user_id):  # noqa: ANN001, ANN202
        return "member"

    monkeypatch.setattr(answer_cache, "answer_key", key)
    monkeypatch.setattr(persistence, "load_user_role", role)


def _deps(llm: FakeLLM, cache: MemoryCache, scope: str = "enterprise") -> runner.RunnerDeps:
    result = RetrievalResult((chunk(1, "Reefer SOP", scope),), low_relevance=False)
    return runner.RunnerDeps(
        pool=None,
        redis=FakeRedis(),
        llm=llm,
        retriever=FakeRetriever(result),  # type: ignore[arg-type]
        settings=AgentSettings(),
        prompts=load_prompts(),
        model_ids={"capable": "m"},
        cache=cache,
    )


def _docs_llm() -> FakeLLM:
    return FakeLLM([guard_json(intent="docs"), "Reefer chat"], [Turn("Refunds take 1 days [1]")])


async def test_company_document_answer_is_replayed_without_llm(db: DB, fixed_key: None) -> None:  # noqa: F811
    cache = MemoryCache()
    await runner.execute_run(_deps(_docs_llm(), cache), "r1", lambda rid: FakeSink())
    assert any(k == "answer" for k, _ in cache.data)
    first_text = db.message_parts[0]["text"]

    llm, sink = FakeLLM([guard_json(intent="docs")]), FakeSink()
    await runner.execute_run(_deps(llm, cache), "r1", lambda rid: sink)
    assert llm.stream_calls == []  # no answer generation: replayed from the cache
    assert db.message_parts[0]["text"] == first_text
    run_part = next(p for p in db.message_parts if p["type"] == "run")
    assert run_part["cached"] is True and db.finished["status"] == "SUCCEEDED"
    assert sink.of(CITATION) and sink.of(CITATION)[0]["scope"] == "enterprise"
    assert ("answer", True) in cache.lookups


async def test_answers_using_personal_documents_are_never_cached(db: DB, fixed_key: None) -> None:  # noqa: F811
    cache = MemoryCache()
    await runner.execute_run(
        _deps(_docs_llm(), cache, scope="personal"), "r1", lambda rid: FakeSink()
    )
    assert not any(k == "answer" for k, _ in cache.data)


async def test_follow_up_questions_skip_the_answer_cache(db: DB, fixed_key: None) -> None:  # noqa: F811
    cache = MemoryCache()
    db.history = [ChatMessage("user", "earlier"), ChatMessage("assistant", "reply")]
    await runner.execute_run(_deps(_docs_llm(), cache), "r1", lambda rid: FakeSink())
    assert not any(kind == "answer" for kind, _ in cache.lookups)
    assert not any(k == "answer" for k, _ in cache.data)


async def test_runs_that_fail_to_save_are_never_cached(
    db: DB,  # noqa: F811
    fixed_key: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(pool, run_id, records):  # noqa: ANN001, ANN202
        raise RuntimeError("database refused the steps")

    monkeypatch.setattr(persistence, "insert_steps", broken)
    cache = MemoryCache()
    await runner.execute_run(_deps(_docs_llm(), cache), "r1", lambda rid: FakeSink())
    assert not any(k == "answer" for k, _ in cache.data)
