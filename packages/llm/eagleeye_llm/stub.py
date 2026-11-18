"""Load-test stand-ins for the model and the embedder (Phase 7A step 6, ADR-34).

Accepted only when APP_ENV=loadtest (Settings refuses LLM_PROVIDER=stub anywhere else). They
cost nothing, answer every call the agent makes with something it can use, and stream at a
realistic speed so the load on the API, workers, Redis and database is close to real traffic.

What a simulated user's message does is chosen by the load-test question pool
(loadtest_questions.json, built by evals/load/build_pool.py and shared with the k6 script); the
stand-in recognises a pool question by its text, so nothing extra appears in the chat:
  docs      a document question: search, then an answer citing [1]
  sql       a database question: query_database with the pool's SQL (the gateway really runs it)
  chart     as sql, then make_chart with the pool's chart
  attack    the guard verdict the pool gives (injection, exfiltration, harmful); attacks marked
            for the data layer pass the guard so the real gateway refuses them
  notebook  list_datasets, then explore_data with a small notebook that runs in the sandbox
Messages outside the pool fall back to tags: #docs, #analysis, otherwise small talk.
"""

import asyncio
import hashlib
import json
import math
import re
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from eagleeye_llm.gateway import ChatMessage, StreamChunk, Tier, ToolCall, ToolSpec, Usage

STUB_MODEL = "stub"
DOCS_TAG = "#docs"
ANALYSIS_TAG = "#analysis"

_LATEST = re.compile(r"<latest_message>\s*(.*?)\s*</latest_message>", re.DOTALL)
_DATASET_ID = re.compile(r"- id ([0-9a-fA-F-]{36})")
_RESULT_ID = re.compile(r"Result id: (\S+)")
_SQL_QUESTION = re.compile(r"\n\nQuestion: (.*?)(?:\n\nPrevious attempts|$)", re.DOTALL)
_NOTEBOOK_GOAL = re.compile(r"\n\nGoal: (.*?)(?:\n\nPrevious attempt|$)", re.DOTALL)
POOL_FILE = Path(__file__).with_name("loadtest_questions.json")

# a small notebook that runs on any data file (shape and types, a summary table, a histogram)
NOTEBOOK = {
    "title": "Data file overview",
    "cells": [
        {
            "purpose": "Shape and column types",
            "code": (
                'df = datasets["ds_1"]\n'
                'print("Shape:", df.shape)\n'
                'display(df.dtypes.astype(str).to_frame("type").head(15))'
            ),
        },
        {
            "purpose": "Summary of the numeric columns",
            "code": (
                'numeric = df.select_dtypes("number")\n'
                'save_table("numeric_summary", numeric.describe().T.round(2))'
            ),
        },
        {
            "purpose": "Distribution of the first numeric column",
            "code": (
                "import matplotlib.pyplot as plt\n"
                "col = numeric.columns[0]\n"
                'numeric[col].plot(kind="hist", bins=30, title=f"Distribution of {col}")\n'
                "plt.tight_layout()"
            ),
        },
    ],
}
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


def _norm(text: str) -> str:
    return " ".join(text.split()).strip().lower()


@cache
def _pool() -> dict[str, dict]:
    """Pool questions by their normalised text (empty when the file is absent)."""
    if not POOL_FILE.exists():
        return {}
    data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    return {_norm(q["text"]): q for q in data["questions"]}


def pool_question(text: str) -> dict | None:
    return _pool().get(_norm(text))


def _chat_title(prompt: str) -> str:
    """The document's title for a pool document question, else the question's first words."""
    question = prompt.split(chr(10) * 2, 1)[-1].strip()
    q = pool_question(question)
    if q and q.get("title"):
        return q["title"]
    return " ".join(question.rstrip("?.!").split()[:8]) or "Load test chat"


def _mode(text: str) -> str:
    q = pool_question(text)
    if q is not None:
        if q["kind"] == "attack":
            return "sql" if q.get("verdict") is None else "attack"
        return q["kind"]
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
        if latest:  # the guard: the verdict and intent the question calls for
            question = latest.group(1)
            mode = _mode(question)
            if mode == "attack":
                verdict = pool_question(question)["verdict"]  # type: ignore[index]
                return json.dumps({"safe": verdict, "intent": "other", "complexity": "simple"})
            intent, complexity = {
                "docs": ("docs", "simple"),
                "sql": ("sql", "simple"),
                "chart": ("sql", "simple"),
                "analysis": ("analysis", "complex"),
                "notebook": ("analysis", "complex"),
            }.get(mode, ("chitchat", "simple"))
            return json.dumps({"safe": "allowed", "intent": intent, "complexity": complexity})
        if "rewrite a user's question for document search" in system:
            question = user.rsplit("Latest question:", 1)[-1].strip()
            return json.dumps(
                {"standalone": question.replace(DOCS_TAG, "").strip(), "variants": []}
            )
        if user.startswith("Today's date:") and "Task:" in user and json_mode:
            return json.dumps(ANALYSIS_DRAFT)  # the analysis agent's code
        sql_question = _SQL_QUESTION.search(user) if json_mode else None
        if sql_question and user.startswith("Today's date:"):  # the SQL writer
            q = pool_question(sql_question.group(1))
            if q and q.get("sql"):
                return json.dumps(
                    {"sql": q["sql"], "title": q.get("title", "Query result"), "assumptions": ""}
                )
            return json.dumps({"unavailable": "Not a load-test question."})
        if json_mode and _NOTEBOOK_GOAL.search(user) and user.startswith("Today's date:"):
            return json.dumps(NOTEBOOK)  # the notebook writer
        if json_mode and "to fix" in user and "Problem:" in user:
            return json.dumps({"code": NOTEBOOK["cells"][0]["code"]})  # a notebook repair
        if json_mode:
            return "{}"
        if len(messages) == 1:  # chat titles are a single user message
            return _chat_title(messages[0].content)
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
        # a short pool answer streams over the same time as a full-length one: same load
        per_word = max(self._t.answer_words, len(words)) / max(len(words), 1)
        delay = per_word / self._t.words_per_s if self._t.words_per_s > 0 else 0.0
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
    mode = _mode(question)
    called = [c.name for m in after for c in m.tool_calls]
    results = "\n".join(m.content for m in after if m.role == "tool")
    if mode in ("sql", "chart"):
        q = pool_question(question)
        if "query_database" in tools and "query_database" not in called:
            asked = q["text"] if q else question
            return ToolCall("stub_query", "query_database", json.dumps({"question": asked}))
        found = _RESULT_ID.search(results)
        if mode == "chart" and q and found and "make_chart" in tools and "make_chart" not in called:
            return ToolCall(
                "stub_chart", "make_chart", json.dumps({**q["chart"], "source_id": found.group(1)})
            )
        return None
    if mode == "notebook":
        if "list_datasets" in tools and "list_datasets" not in called:
            return ToolCall("stub_list", "list_datasets", "{}")
        found = _DATASET_ID.search(results)
        if found and "explore_data" in tools and "explore_data" not in called:
            args = {"goal": "Explore this data file", "inputs": [found.group(1)]}
            return ToolCall("stub_explore", "explore_data", json.dumps(args))
        return None
    if mode != "analysis":
        return None
    if "list_datasets" in tools and "list_datasets" not in called:
        return ToolCall("stub_list", "list_datasets", "{}")
    if "analyze_data" in tools and "analyze_data" not in called:
        found = _DATASET_ID.search(results)
        if found:
            args = {"question": "Count the rows in this data file", "inputs": [found.group(1)]}
            return ToolCall("stub_analyze", "analyze_data", json.dumps(args))
    return None


_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_MARKUP = re.compile(r"[#*_|`>]+")
SQL_ANSWER = (
    "Here is what the Grand Line operations database shows for this question. The results "
    "of the query are in the table above, straight from the data, with nothing added."
)
CHART_ANSWER = (
    "Here is what the Grand Line operations database shows for this question. The query "
    "results are in the table above, and the chart is drawn from the same rows."
)
NOTEBOOK_ANSWER = (
    "The analysis ran in the isolated sandbox on your data file. The notebook above "
    "profiles each column, checks for gaps and summarises the main measures."
)


def _quote(passages: str, span: str) -> str | None:
    """The sentence of a retrieved passage that states the fact, cleaned of Markdown."""
    for raw in _SENTENCE.split(passages):
        sentence = _MARKUP.sub(" ", raw).strip()
        sentence = re.sub(r"^\[\d+\]\s*", "", " ".join(sentence.split()))
        if span.lower() in sentence.lower() and len(sentence) <= 320:
            return sentence.rstrip(".") + "."
    return None


def _find_pool_question(messages: list[ChatMessage]) -> dict | None:
    """The pool question this conversation is answering: the latest user message itself, or
    (when the answer prompt wraps the question with tool results) the longest pool question
    quoted in it."""
    question, _ = _since_question(messages)
    q = pool_question(question)
    if q:
        return q
    text = _norm(question)
    quoted = [q for key, q in _pool().items() if key in text]
    return max(quoted, key=lambda q: len(q["text"])) if quoted else None


def _pool_answer(messages: list[ChatMessage]) -> str | None:
    """A believable answer for a pool question (shown in the recorded windows)."""
    q = _find_pool_question(messages)
    if not q:
        return None
    if q["kind"] == "docs" and q.get("span"):
        passages = "\n".join(m.content for m in messages if m.role in ("system", "tool", "user"))
        quoted = _quote(passages, q["span"])
        if quoted:
            return f"According to the {q['title']}: {quoted} [1]"
        return f"According to the {q['title']}, the answer is {q['span']}. [1]"
    return {"sql": SQL_ANSWER, "chart": CHART_ANSWER, "notebook": NOTEBOOK_ANSWER}.get(q["kind"])


def _answer_words(messages: list[ChatMessage], count: int) -> list[str]:
    pooled = _pool_answer(messages)
    if pooled:
        return pooled.split()
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
