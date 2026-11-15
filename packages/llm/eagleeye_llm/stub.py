"""Load-test stand-ins for the model and the embedder (Phase 7A step 6, ADR-34).

Accepted only when APP_ENV=loadtest (Settings refuses LLM_PROVIDER=stub anywhere else). They
cost nothing, answer every call the agent makes with something it can use, and stream at a
realistic speed so the load on the API, workers, Redis and database is close to real traffic.

What a simulated user's message does is chosen by a tag in it:
  #docs      a document question: search, then an answer citing [1]
  #analysis  a data-file analysis: list_datasets → analyze_data (real code in the sandbox)
  otherwise  small talk: a plain streamed answer
"""

import asyncio
import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

from eagleeye_llm.gateway import ChatMessage, StreamChunk, Tier, ToolCall, ToolSpec, Usage

STUB_MODEL = "stub"
DOCS_TAG = "#docs"
ANALYSIS_TAG = "#analysis"

_LATEST = re.compile(r"<latest_message>\s*(.*?)\s*</latest_message>", re.DOTALL)
_DATASET_ID = re.compile(r"- id ([0-9a-fA-F-]{36})")
_WORD = re.compile(r"[a-z0-9]+")

ANSWER_TEXT = (
    "Here is a summary based on the information available. The main points are set out "
    "below in plain terms, with the most important details first and the supporting context "
    "after them. If anything is unclear, ask a follow-up question and I will go into more "
    "detail on that part. "
)
# a query the analysis sandbox can run on any table: no numbers for the model to invent
ANALYSIS_DRAFT = {
    "mode": "sql",
    "code": "SELECT COUNT(*) AS row_count FROM ds_1",
    "title": "Row count",
    "assumptions": "",
}


@dataclass(frozen=True)
class StubTiming:
    first_token_s: float = 0.6  # the model "thinking" before the first word
    words_per_s: float = 12.0  # streaming speed of a typical answer
    answer_words: int = 120  # about 10 s per answer at the default speed
    complete_s: float = 0.3  # a short non-streamed call (guard, rewrite, title)


def _mode(text: str) -> str:
    lowered = text.lower()
    if ANALYSIS_TAG in lowered:
        return "analysis"
    if DOCS_TAG in lowered:
        return "docs"
    return "chitchat"


def _usage(tokens_in: int, tokens_out: int) -> Usage:
    return Usage(tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=0.0, model_id=STUB_MODEL)


def _approx_tokens(messages: Sequence[ChatMessage]) -> int:
    return sum(len(m.content) for m in messages) // 4


class StubLLM:
    """LLMGateway with canned replies. Never makes a network call."""

    def __init__(self, timing: StubTiming | None = None) -> None:
        self._t = timing or StubTiming()

    async def complete(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 1024,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> tuple[str, Usage]:
        await asyncio.sleep(self._t.complete_s)
        text = self._reply(messages, json_mode)
        return text, _usage(_approx_tokens(messages), len(text) // 4)

    def _reply(self, messages: list[ChatMessage], json_mode: bool) -> str:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        latest = _LATEST.search(user)
        if latest:  # the guard: safe, with the intent the tag asks for
            mode = _mode(latest.group(1))
            intent, complexity = {
                "docs": ("docs", "simple"),
                "analysis": ("analysis", "complex"),
            }.get(mode, ("chitchat", "simple"))
            return json.dumps({"safe": "allowed", "intent": intent, "complexity": complexity})
        if "rewrite a user's question for document search" in system:
            question = user.rsplit("Latest question:", 1)[-1].strip()
            return json.dumps(
                {"standalone": question.replace(DOCS_TAG, "").strip(), "variants": []}
            )
        if user.startswith("Today's date:") and "Task:" in user and json_mode:
            return json.dumps(ANALYSIS_DRAFT)  # the analysis agent's code
        if json_mode:
            return "{}"
        if len(messages) == 1:  # chat titles are a single user message
            return "Load test chat"
        return "A sample data file used for load testing."

    async def stream(
        self,
        tier: Tier,
        messages: list[ChatMessage],
        max_tokens: int = 2048,
        tools: Sequence[ToolSpec] | None = None,
    ) -> AsyncIterator[StreamChunk]:
        await asyncio.sleep(self._t.first_token_s)
        call = _next_tool_call(messages, {t.name for t in tools or ()})
        if call is not None:
            yield StreamChunk(
                done=True,
                usage=_usage(_approx_tokens(messages), 20),
                model_id=STUB_MODEL,
                tool_calls=(call,),
            )
            return
        words = _answer_words(messages, self._t.answer_words)
        delay = 1.0 / self._t.words_per_s if self._t.words_per_s > 0 else 0.0
        for word in words:
            yield StreamChunk(text=word + " ", model_id=STUB_MODEL)
            await asyncio.sleep(delay)
        yield StreamChunk(
            done=True,
            usage=_usage(_approx_tokens(messages), len(words) * 4 // 3),
            model_id=STUB_MODEL,
        )


def _since_question(messages: list[ChatMessage]) -> tuple[str, list[ChatMessage]]:
    """The latest user message and everything after it (tool calls and results)."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].role == "user":
            return messages[i].content, messages[i + 1 :]
    return "", []


def _next_tool_call(messages: list[ChatMessage], tools: set[str]) -> ToolCall | None:
    question, after = _since_question(messages)
    if _mode(question) != "analysis":
        return None
    called = [c.name for m in after for c in m.tool_calls]
    if "list_datasets" in tools and "list_datasets" not in called:
        return ToolCall("stub_list", "list_datasets", "{}")
    if "analyze_data" in tools and "analyze_data" not in called:
        results = "\n".join(m.content for m in after if m.role == "tool")
        found = _DATASET_ID.search(results)
        if found:
            args = {"question": "Count the rows in this data file", "inputs": [found.group(1)]}
            return ToolCall("stub_analyze", "analyze_data", json.dumps(args))
    return None


def _answer_words(messages: list[ChatMessage], count: int) -> list[str]:
    grounded = any("[1]" in m.content for m in messages if m.role in ("system", "tool", "user"))
    text = ANSWER_TEXT * (count // len(ANSWER_TEXT.split()) + 1)
    words = text.split()[:count]
    if grounded and words:
        words[-1] += " [1]"  # cite the first passage, as a grounded answer would
    return words


class StubEmbedder:
    """Feature-hashed bag of words: texts that share words get similar vectors, so search
    still finds the seeded documents. Deterministic, no network."""

    def __init__(self, dim: int) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        for word in _WORD.findall(text.lower()):
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dim
            vec[index] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [x / norm for x in vec]
