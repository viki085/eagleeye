"""Scripted test doubles for the agent graph."""

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from eagleeye_agents.budgets import BudgetLimits
from eagleeye_agents.context import AgentSettings, DocInfo, RunContext
from eagleeye_agents.control import CancelToken
from eagleeye_agents.prompts.loader import load_prompts
from eagleeye_llm.gateway import ChatMessage, StreamChunk, ToolCall, ToolSpec, Usage
from eagleeye_retrieval.types import AccessScope, RetrievalResult, RetrievedChunk


def guard_json(safe: str = "allowed", intent: str = "chitchat", complexity: str = "simple") -> str:
    return json.dumps({"safe": safe, "intent": intent, "complexity": complexity})


@dataclass(frozen=True)
class Turn:
    """One scripted streamed LLM turn."""

    text: str = ""
    calls: tuple[ToolCall, ...] = ()
    cost: float = 0.001


def call(name: str, args: dict | None = None, id_: str = "") -> ToolCall:
    return ToolCall(id_ or f"call_{name}", name, json.dumps(args or {}))


class CutOff(str):
    """A completion the model stopped writing because it hit max_tokens."""


class FakeLLM:
    def __init__(
        self, completions: Sequence[str | Exception] = (), turns: Sequence[Turn] = ()
    ) -> None:
        self.completions = list(completions)
        self.turns = list(turns)
        self.stream_calls: list[dict[str, Any]] = []
        self.complete_calls: list[list[ChatMessage]] = []
        self.max_tokens_seen: list[int] = []

    async def complete(self, tier, messages, max_tokens=1024, json_mode=False, temperature=None):  # noqa: ANN001
        self.complete_calls.append(messages)
        self.max_tokens_seen.append(max_tokens)
        item = self.completions.pop(0) if self.completions else guard_json()
        if isinstance(item, Exception):
            raise item
        if isinstance(item, CutOff):  # the reply used the whole allowance and stopped mid-way
            return str(item), Usage(5, max_tokens, 0.0001, "fast-model")
        return item, Usage(5, 5, 0.0001, "fast-model")

    async def stream(
        self,
        tier,
        messages,
        max_tokens=2048,
        tools: Sequence[ToolSpec] | None = None,  # noqa: ANN001
    ) -> AsyncIterator[StreamChunk]:
        self.stream_calls.append({"messages": messages, "tools": tools})
        turn = self.turns.pop(0) if self.turns else Turn("ok")
        for word in turn.text.split(" ") if turn.text else []:
            yield StreamChunk(text=word + " ")
        yield StreamChunk(
            done=True, usage=Usage(10, 10, turn.cost, "capable-model"), tool_calls=turn.calls
        )


class FakeSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event: str, data: dict) -> None:
        self.events.append((event, data))

    def names(self) -> list[str]:
        return [e for e, _ in self.events]

    def of(self, name: str) -> list[dict]:
        return [d for e, d in self.events if e == name]


def chunk(i: int, title: str = "Policy", scope: str = "personal") -> RetrievedChunk:
    return RetrievedChunk(
        f"c{i}", f"d{i}", title, scope, i, i, ("Returns",), f"Refunds take {i} days.", 0.5
    )


@dataclass
class FakeRetriever:
    result: RetrievalResult = field(
        default_factory=lambda: RetrievalResult((chunk(1),), low_relevance=False)
    )
    calls: list[tuple[str, AccessScope, bool]] = field(default_factory=list)

    async def retrieve(self, question, history, scope, rewrite=True):  # noqa: ANN001
        self.calls.append((question, scope, rewrite))
        return self.result


@dataclass
class FakeStore:
    docs: list[DocInfo] = field(default_factory=lambda: [DocInfo("d1", "Policy", "personal", 3, 3)])
    security_events: list[tuple[str, str, dict]] = field(default_factory=list)

    async def visible_ready_documents(self, user_id: str) -> list[DocInfo]:
        return self.docs

    async def record_security_event(self, user_id, run_id, kind, category, detail) -> None:  # noqa: ANN001
        self.security_events.append((kind, category, detail))


def make_ctx(
    llm: FakeLLM,
    retriever: FakeRetriever | None = None,
    store: FakeStore | None = None,
    limits: BudgetLimits | None = None,
    cancelled: bool = False,
) -> tuple[RunContext, FakeSink, FakeStore]:
    sink, st = FakeSink(), store or FakeStore()

    async def is_set() -> bool:
        return cancelled

    ctx = RunContext.create(
        run_id="r1",
        chat_id="chat1",
        user_id="u1",
        llm=llm,
        retriever=retriever or FakeRetriever(),
        store=st,
        sink=sink,
        cancel=CancelToken(is_set),
        prompts=load_prompts(),
        settings=AgentSettings(limits=limits or BudgetLimits()),
    )
    return ctx, sink, st
