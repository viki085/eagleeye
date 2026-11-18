"""Stand-in model, driven by the load-test question pool: each kind of question takes its real
path (database, chart, attack, notebook) with nothing extra shown in the chat."""

import json

import pytest
from eagleeye_llm.gateway import ChatMessage, ToolCall, ToolSpec
from eagleeye_llm.stub import POOL_FILE, StubLLM, StubTiming, pool_question

FAST = StubTiming(first_token_s=0, words_per_s=0, answer_words=20, complete_s=0)
SPEC = {"type": "object", "properties": {}}
TOOLS = [
    ToolSpec(n, n, SPEC)
    for n in ("search_knowledge", "query_database", "make_chart", "list_datasets", "explore_data")
]
POOL = json.loads(POOL_FILE.read_text(encoding="utf-8"))
DATASET = "22222222-2222-2222-2222-222222222222"


def first(kind: str, **match: object) -> dict:
    return next(
        q
        for q in POOL["questions"]
        if q["kind"] == kind and all(q.get(k) == v for k, v in match.items())
    )


def guard(text: str) -> list[ChatMessage]:
    user = f"User's documents: (none)\n\n<latest_message>\n{text}\n</latest_message>"
    return [ChatMessage("system", "You classify messages."), ChatMessage("user", user)]


async def calls_after(messages: list[ChatMessage]) -> tuple[ToolCall, ...]:
    calls: tuple[ToolCall, ...] = ()
    async for chunk in StubLLM(FAST).stream("capable", messages, tools=TOOLS):
        if chunk.done:
            calls = chunk.tool_calls
    return calls


def test_pool_has_every_kind_and_the_agreed_mix() -> None:
    kinds = {q["kind"] for q in POOL["questions"]}
    assert kinds == {"docs", "sql", "chart", "attack", "notebook"}
    assert POOL["weights"] == {"docs": 90, "sql": 3, "chart": 3, "attack": 3, "notebook": 1}
    assert len({q["attack"] for q in POOL["questions"] if q["kind"] == "attack"}) >= 8
    assert pool_question("  " + first("docs")["text"].upper() + " ") is not None  # matched loosely


@pytest.mark.parametrize(
    ("kind", "safe", "intent"),
    [
        ("docs", "allowed", "docs"),
        ("sql", "allowed", "sql"),
        ("chart", "allowed", "sql"),
        ("notebook", "allowed", "analysis"),
    ],
)
async def test_guard_intent_follows_the_pool(kind: str, safe: str, intent: str) -> None:
    raw, _ = await StubLLM(FAST).complete("fast", guard(first(kind)["text"]), json_mode=True)
    verdict = json.loads(raw)
    assert verdict["safe"] == safe and verdict["intent"] == intent


async def test_attacks_get_their_verdict_or_pass_to_the_data_layer() -> None:
    blocked = first("attack", attack="harmful")
    raw, _ = await StubLLM(FAST).complete("fast", guard(blocked["text"]), json_mode=True)
    assert json.loads(raw)["safe"] == "harmful"
    refused_later = first("attack", attack="sql_injection")  # the real gateway must refuse it
    raw, _ = await StubLLM(FAST).complete("fast", guard(refused_later["text"]), json_mode=True)
    assert json.loads(raw) == {"safe": "allowed", "intent": "sql", "complexity": "simple"}


async def test_sql_writer_returns_the_pool_sql() -> None:
    q = first("chart")
    user = f"Today's date: 2026-11-18\n\nQuestion: {q['text']}"
    raw, _ = await StubLLM(FAST).complete(
        "capable", [ChatMessage("system", "Write SQL"), ChatMessage("user", user)], json_mode=True
    )
    assert json.loads(raw)["sql"] == q["sql"]


async def test_chart_question_queries_then_charts_the_result() -> None:
    q = first("chart")
    history = [ChatMessage("system", "sup"), ChatMessage("user", q["text"])]
    calls = await calls_after(history)
    assert (
        calls[0].name == "query_database"
        and json.loads(calls[0].arguments_json)["question"] == q["text"]
    )
    history += [
        ChatMessage("assistant", "", tool_calls=calls),
        ChatMessage("tool", "Result id: art_123 — 'x'\n...", tool_call_id=calls[0].id),
    ]
    calls = await calls_after(history)
    args = json.loads(calls[0].arguments_json)
    assert (
        calls[0].name == "make_chart"
        and args["source_id"] == "art_123"
        and args["x"] == q["chart"]["x"]
    )


async def test_notebook_question_lists_files_then_explores() -> None:
    q = first("notebook")
    history = [ChatMessage("system", "sup"), ChatMessage("user", q["text"])]
    calls = await calls_after(history)
    assert calls[0].name == "list_datasets"
    history += [
        ChatMessage("assistant", "", tool_calls=calls),
        ChatMessage("tool", f"- id {DATASET} voyages", tool_call_id=calls[0].id),
    ]
    calls = await calls_after(history)
    assert calls[0].name == "explore_data" and json.loads(calls[0].arguments_json)["inputs"] == [
        DATASET
    ]


async def test_notebook_writer_returns_runnable_cells() -> None:
    user = "Today's date: 2026-11-18\n\nGoal: Explore this data file"
    raw, _ = await StubLLM(FAST).complete(
        "capable",
        [ChatMessage("system", "Write a notebook"), ChatMessage("user", user)],
        json_mode=True,
    )
    draft = json.loads(raw)
    assert len(draft["cells"]) == 3 and 'datasets["ds_1"]' in draft["cells"][0]["code"]


async def answer_after(messages: list[ChatMessage], tools: list[ToolSpec] = TOOLS) -> str:
    text = ""
    async for chunk in StubLLM(FAST).stream("capable", messages, tools=tools):
        text += chunk.text or ""
    return text.strip()


async def test_document_answers_quote_the_passage_with_the_fact() -> None:
    q = first("docs", doc="emissions-policy")
    passage = (
        "[1] Emissions policy, section 3\n# Targets\nThe fleet must cut CO2 per TEU-km by "
        f"{q['span']} by 2030 against the 2024 baseline. Progress is reported each quarter."
    )
    answer = await answer_after(
        [ChatMessage("system", "sup"), ChatMessage("user", q["text"]), ChatMessage("tool", passage)]
    )
    assert answer.startswith(f"According to the {q['title']}")
    assert f"by {q['span']} by 2030" in answer and answer.count("[1]") == 1
    assert "Here is a summary" not in answer and "#" not in answer


async def test_document_answers_fall_back_to_the_fact_when_no_passage_has_it() -> None:
    q = first("docs", doc="emissions-policy")
    answer = await answer_after(
        [ChatMessage("system", "sup"), ChatMessage("user", q["text"]), ChatMessage("tool", "[1] x")]
    )
    assert q["span"] in answer and q["title"] in answer and "[1]" in answer


async def test_database_and_notebook_answers_point_to_their_results() -> None:
    sql = await answer_after(
        [ChatMessage("system", "s"), ChatMessage("user", first("sql")["text"])], []
    )
    chart = await answer_after(
        [ChatMessage("system", "s"), ChatMessage("user", first("chart")["text"])], []
    )
    book = await answer_after(
        [ChatMessage("system", "s"), ChatMessage("user", first("notebook")["text"])], []
    )
    assert "operations database" in sql and "chart" in chart and "sandbox" in book
    assert not any(ch.isdigit() for ch in sql + chart)  # no figures the checks could not verify
