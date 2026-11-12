from types import SimpleNamespace as NS

import pytest
from eagleeye_llm import litellm_adapter as adapter
from eagleeye_llm.gateway import ChatMessage, ToolCall, ToolSpec


def _tc(index: int, id_: str | None = None, name: str | None = None, args: str | None = None):  # noqa: ANN202
    return NS(index=index, id=id_, function=NS(name=name, arguments=args))


def _chunk(content: str | None = None, tool_calls: list | None = None, usage=None):  # noqa: ANN001, ANN202
    return NS(choices=[NS(delta=NS(content=content, tool_calls=tool_calls))], usage=usage)


class _Stream:
    def __init__(self, chunks: list) -> None:
        self._chunks = chunks

    def __aiter__(self):  # noqa: ANN204
        async def gen():  # noqa: ANN202
            for c in self._chunks:
                yield c

        return gen()


def test_assembler_joins_fragments_across_chunks() -> None:
    a = adapter.ToolCallAssembler()
    a.add([_tc(0, "call_a", "search_knowledge", '{"que'), _tc(1, "call_b", "list_documents", "{}")])
    a.add([_tc(0, None, None, 'ry": "refunds"}')])
    calls = a.calls()
    assert calls == (
        ToolCall("call_a", "search_knowledge", '{"query": "refunds"}'),
        ToolCall("call_b", "list_documents", "{}"),
    )


def test_to_wire_includes_tool_fields() -> None:
    msgs = [
        ChatMessage("assistant", "", tool_calls=(ToolCall("c1", "t", "{}"),)),
        ChatMessage("tool", "result", tool_call_id="c1"),
    ]
    wire = adapter.to_wire(msgs)
    assert wire[0]["tool_calls"][0]["function"] == {"name": "t", "arguments": "{}"}
    assert wire[1]["tool_call_id"] == "c1" and wire[1]["role"] == "tool"


def test_tool_schemas_shape() -> None:
    spec = ToolSpec("t", "desc", {"type": "object", "properties": {}})
    assert adapter.tool_schemas([spec])[0]["function"]["name"] == "t"


async def test_stream_yields_text_then_done_with_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = NS(prompt_tokens=10, completion_tokens=5)
    stream = _Stream(
        [
            _chunk("Hel"),
            _chunk("lo"),
            _chunk(tool_calls=[_tc(0, "c1", "list_documents", "{}")]),
            NS(choices=[], usage=usage),
        ]
    )
    captured: dict = {}

    async def fake_acompletion(**kw):  # noqa: ANN003, ANN202
        captured.update(kw)
        return stream

    monkeypatch.setattr(adapter.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(adapter, "price", lambda *a: 0.01)
    gw = adapter.LiteLLMGateway("fast-m", "cap-m")
    out = [
        c
        async for c in gw.stream(
            "capable", [ChatMessage("user", "hi")], tools=[ToolSpec("x", "d", {})]
        )
    ]
    assert "".join(c.text for c in out if not c.done) == "Hello"
    done = out[-1]
    assert done.done and done.tool_calls[0].name == "list_documents"
    assert done.usage.tokens_in == 10 and done.usage.cost_usd == 0.01 and not done.usage.degraded
    assert captured["tools"][0]["function"]["name"] == "x"


async def test_complete_falls_back_and_marks_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    models: list[str] = []

    async def fake_acompletion(**kw):  # noqa: ANN003, ANN202
        models.append(kw["model"])
        if kw["model"] == "primary":
            raise RuntimeError("503")
        assert kw["response_format"] == {"type": "json_object"}
        return NS(
            choices=[NS(message=NS(content="{}"))], usage=NS(prompt_tokens=1, completion_tokens=1)
        )

    monkeypatch.setattr(adapter.litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(adapter, "price", lambda *a: 0.0)
    gw = adapter.LiteLLMGateway("primary", "cap", fallback_fast="backup")
    text, usage = await gw.complete("fast", [ChatMessage("user", "x")], json_mode=True)
    assert text == "{}" and usage.degraded and usage.model_id == "backup"
    assert models == ["primary", "backup"]


async def test_complete_without_fallback_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(**kw):  # noqa: ANN003, ANN202
        raise RuntimeError("down")

    monkeypatch.setattr(adapter.litellm, "acompletion", boom)
    with pytest.raises(RuntimeError):
        await adapter.LiteLLMGateway("a", "b").complete("fast", [ChatMessage("user", "x")])


def test_unknown_price_uses_reference_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_cost(model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, float]:
        if model == "mystery":
            raise ValueError("unknown")
        return 0.25, 0.25

    monkeypatch.setattr(adapter.litellm, "cost_per_token", fake_cost)
    assert adapter.price("mystery", 1, 1, "gpt-4o") == 0.5


def test_real_pricing_table_prices_known_model() -> None:
    """Guards against LiteLLM API drift silently zeroing every cost (found in Phase 3 E2E)."""
    assert adapter.price("gpt-4o", 1000, 500, "gpt-4o") > 0
