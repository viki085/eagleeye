from dataclasses import dataclass, field

import pytest

from eagleeye_llm.gateway import StreamChunk, Usage
from eagleeye_retrieval.types import RetrievedChunk

from app.services import run_executor as ex
from app.services.grounding import Grounding

CHUNK = RetrievedChunk("c1", "d1", "Policy", "personal", 0, 2, ("Returns",), "30 days.", 0.6)


def _msg(role: str, text: str) -> dict:
    return {"role": role, "parts": {"parts": [{"type": "text", "text": text}]}}


class _LLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list = []

    async def stream(self, tier, messages, max_tokens=2048):  # noqa: ANN001
        self.prompts.append(messages)
        for word in self.reply.split(" "):
            yield StreamChunk(text=word + " ")
        yield StreamChunk(done=True, usage=Usage(10, 5, 0.001))

    async def complete(self, tier, messages, max_tokens=1024):  # noqa: ANN001
        return "Title", Usage()


@dataclass
class _Harness:
    events: list = field(default_factory=list)
    persisted: list = field(default_factory=list)
    finished: list = field(default_factory=list)


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> _Harness:
    h = _Harness()

    class _Sink:
        def __init__(self, redis, run_id):  # noqa: ANN001
            pass

        async def emit(self, event, data):  # noqa: ANN001
            h.events.append((event, data))

    async def list_messages(pool, chat_id):  # noqa: ANN001
        return [_msg("user", "hi"), _msg("assistant", "hello"), _msg("user", "refund window?")]

    async def noop(*a, **k):  # noqa: ANN002, ANN003
        return None

    async def finished(pool, run_id, status, **kw):  # noqa: ANN001, ANN003
        h.finished.append(status)

    async def persist(pool, chat_id, run_id, answer, citations, usage):  # noqa: ANN001
        h.persisted.append((answer, citations))
        return {"id": "m1"}

    monkeypatch.setattr(ex, "EventSink", _Sink)
    monkeypatch.setattr(ex.messages_repo, "list_messages", list_messages)
    monkeypatch.setattr(ex.runs_repo, "mark_running", noop)
    monkeypatch.setattr(ex.runs_repo, "mark_finished", finished)
    monkeypatch.setattr(ex, "_persist_answer", persist)
    return h


def _use_grounding(monkeypatch: pytest.MonkeyPatch, g: Grounding | None) -> None:
    async def fake_ground_for_run(*a):  # noqa: ANN002
        return g

    monkeypatch.setattr(ex, "_ground_for_run", fake_ground_for_run)


async def test_grounded_run_emits_citations_and_persists_them(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_grounding(monkeypatch, Grounding((CHUNK,), explicit=False))
    llm = _LLM("Refunds take 30 days [1].")
    await ex.execute_run(None, None, llm, "r1", "chat1", "u1")

    names = [e for e, _ in harness.events]
    assert names[0] == "run.started" and names[-1] == "run.done"
    assert names.index("citation") < names.index("run.done")
    assert harness.persisted[0][1][0].chunk_id == "c1"
    assert harness.finished == ["SUCCEEDED"]
    system = llm.prompts[0][0]
    assert system.role == "system" and "<context>" in system.content


async def test_plain_run_uses_default_prompt_without_citations(
    harness: _Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_grounding(monkeypatch, None)
    llm = _LLM("Hello [1] there.")
    await ex.execute_run(None, None, llm, "r1", "chat1", "u1")
    assert "citation" not in [e for e, _ in harness.events]
    assert llm.prompts[0][0].content == ex.SYSTEM_PROMPT
    assert harness.persisted[0][1] == []


async def test_failure_emits_run_error(harness: _Harness, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*a):  # noqa: ANN002
        raise RuntimeError("db down")

    monkeypatch.setattr(ex, "_ground_for_run", boom)
    await ex.execute_run(None, None, _LLM("x"), "r1", "chat1", "u1")
    assert harness.events[-1][0] == "run.error" and harness.finished == ["FAILED"]


def test_build_prompt_keeps_history_after_system() -> None:
    rows = [_msg("user", "a"), _msg("assistant", "b")]
    prompt = ex.build_prompt(rows, Grounding((), explicit=True))
    assert [m.role for m in prompt] == ["system", "user", "assistant"]
    assert "don't appear to cover" in prompt[0].content
