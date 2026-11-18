"""Load-test stub model and embedder: every call the agent makes gets a usable answer."""

import json
import math

import pytest
from eagleeye_core.config import Settings
from eagleeye_llm.factory import build_embedder, build_llm
from eagleeye_llm.gateway import ChatMessage, ToolCall, ToolSpec
from eagleeye_llm.litellm_adapter import LiteLLMGateway
from eagleeye_llm.stub import StubEmbedder, StubLLM, StubTiming

FAST = StubTiming(first_token_s=0, words_per_s=0, answer_words=30, complete_s=0)
SPEC = {"type": "object", "properties": {}}
TOOLS = [ToolSpec(n, n, SPEC) for n in ("search_knowledge", "list_datasets", "analyze_data")]
DATASET = "11111111-1111-1111-1111-111111111111"


def guard_input(question: str) -> list[ChatMessage]:
    user = f"User's documents: (none)\n\n<latest_message>\n{question}\n</latest_message>"
    return [ChatMessage("system", "You classify messages."), ChatMessage("user", user)]


async def collect(llm: StubLLM, messages: list[ChatMessage]) -> tuple[str, tuple[ToolCall, ...]]:
    text, calls = "", ()
    async for chunk in llm.stream("capable", messages, tools=TOOLS):
        text += chunk.text
        if chunk.done:
            calls = chunk.tool_calls
            assert chunk.usage.cost_usd == 0.0 and chunk.usage.model_id == "stub"
    return text, calls


@pytest.mark.parametrize(
    ("question", "intent", "complexity"),
    [
        ("hello there", "chitchat", "simple"),
        ("#docs what is the travel policy?", "docs", "simple"),
        ("#analysis compare orders by region", "analysis", "complex"),
    ],
)
async def test_guard_verdict_follows_the_tag(question: str, intent: str, complexity: str) -> None:
    raw, usage = await StubLLM(FAST).complete("fast", guard_input(question), json_mode=True)
    assert json.loads(raw) == {"safe": "allowed", "intent": intent, "complexity": complexity}
    assert usage.cost_usd == 0.0


async def test_rewrite_title_and_analysis_code() -> None:
    llm = StubLLM(FAST)
    rewrite_system = "You rewrite a user's question for document search.\nReturn JSON."
    raw, _ = await llm.complete(
        "fast",
        [
            ChatMessage("system", rewrite_system),
            ChatMessage("user", "Conversation:\n(none)\n\nLatest question:\n#docs leave rules"),
        ],
    )
    assert json.loads(raw)["standalone"] == "leave rules"
    title, _ = await llm.complete("fast", [ChatMessage("user", "Title this chat\n\nhello")])
    assert title == "hello"  # the question's first words, as a person would name it
    code, _ = await llm.complete(
        "capable",
        [ChatMessage("system", "Write code"), ChatMessage("user", "Today's date: x\n\nTask: y")],
        json_mode=True,
    )
    assert "ds_1" in json.loads(code)["code"]


async def test_small_talk_streams_a_plain_answer() -> None:
    text, calls = await collect(StubLLM(FAST), [ChatMessage("user", "hi")])
    assert calls == () and len(text.split()) == 30 and "[1]" not in text


async def test_grounded_answer_cites_the_first_passage() -> None:
    messages = [
        ChatMessage("system", "<context>[1] Travel policy</context>"),
        ChatMessage("user", "#docs travel?"),
    ]
    text, _ = await collect(StubLLM(FAST), messages)
    assert text.strip().endswith("[1]")


async def test_analysis_lists_files_then_analyses_then_answers() -> None:
    llm = StubLLM(FAST)
    history = [ChatMessage("system", "sup"), ChatMessage("user", "#analysis orders by region")]
    _, calls = await collect(llm, history)
    assert [c.name for c in calls] == ["list_datasets"]
    history += [
        ChatMessage("assistant", "", tool_calls=calls),
        ChatMessage(
            "tool", f"DATA FILES\n- id {DATASET}: 'sales' (48 rows)", tool_call_id=calls[0].id
        ),
    ]
    _, calls = await collect(llm, history)
    assert calls[0].name == "analyze_data"
    assert json.loads(calls[0].arguments_json)["inputs"] == [DATASET]
    history += [
        ChatMessage("assistant", "", tool_calls=calls),
        ChatMessage("tool", "result table", tool_call_id=calls[0].id),
    ]
    text, calls = await collect(llm, history)
    assert calls == () and text


async def test_analysis_without_data_files_answers_instead_of_looping() -> None:
    history = [
        ChatMessage("user", "#analysis orders"),
        ChatMessage("assistant", "", tool_calls=(ToolCall("a", "list_datasets", "{}"),)),
        ChatMessage("tool", "No data files uploaded.", tool_call_id="a"),
    ]
    _, calls = await collect(StubLLM(FAST), history)
    assert calls == ()


async def test_embedder_is_deterministic_normalised_and_word_sensitive() -> None:
    emb = StubEmbedder(64)
    a, a2, b, empty = await emb.embed(
        ["travel policy flights", "travel policy flights", "security laptops", ""]
    )
    assert a == a2 and len(a) == 64
    assert math.isclose(sum(x * x for x in a), 1.0) and math.isclose(sum(x * x for x in empty), 1.0)
    (query,) = await emb.embed(["what is the travel policy"])
    dot = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    assert dot(query, a) > dot(query, b)


def _loadtest(**kw: object) -> Settings:
    keys = {"s3_access_key": "k", "s3_secret_key": "s"}  # test values, not the local defaults
    return Settings(_env_file=None, app_env="loadtest", **keys, **kw)


def test_factory_builds_the_stub_only_when_asked() -> None:
    assert isinstance(build_llm(_loadtest(llm_provider="stub")), StubLLM)
    assert isinstance(build_embedder(_loadtest(llm_provider="stub", embed_dim=8)), StubEmbedder)
    assert isinstance(build_llm(_loadtest()), LiteLLMGateway)


def test_factory_refuses_the_stub_outside_loadtest_even_past_settings() -> None:
    # model_construct skips validation: the factory must still refuse
    s = Settings.model_construct(app_env="production", llm_provider="stub", embed_dim=8)
    with pytest.raises(RuntimeError, match="APP_ENV=loadtest"):
        build_llm(s)
    with pytest.raises(RuntimeError, match="APP_ENV=loadtest"):
        build_embedder(s)
