from eagleeye_llm.gateway import ChatMessage, Usage
from eagleeye_retrieval.rewrite import MAX_QUERY_CHARS, parse_rewrite, rewrite_query


def test_parse_valid_json() -> None:
    raw = '{"standalone": "What is the refund window?", "variants": ["refund days", "returns"]}'
    assert parse_rewrite(raw, "q") == ["What is the refund window?", "refund days", "returns"]


def test_parse_fenced_json() -> None:
    raw = '```json\n{"standalone": "A", "variants": []}\n```'
    assert parse_rewrite(raw, "q") == ["A"]


def test_parse_garbage_falls_back() -> None:
    assert parse_rewrite("not json at all", "original") == ["original"]
    assert parse_rewrite("[1, 2]", "original") == ["original"]
    assert parse_rewrite('{"variants": [1, 2]}', "original") == ["original"]


def test_parse_dedupes_and_caps() -> None:
    raw = '{"standalone": "Same", "variants": ["same", "x", "y", "z", "w"]}'
    assert parse_rewrite(raw, "q") == ["Same", "x", "y"]


def test_parse_truncates_long_queries() -> None:
    raw = '{"standalone": "' + "a" * 2000 + '"}'
    assert len(parse_rewrite(raw, "q")[0]) == MAX_QUERY_CHARS


class _FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    async def complete(self, tier, messages, max_tokens=1024):  # noqa: ANN001
        self.calls.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, Usage()

    def stream(self, tier, messages, max_tokens=2048):  # noqa: ANN001
        raise NotImplementedError


async def test_rewrite_uses_fast_tier_and_history() -> None:
    llm = _FakeLLM('{"standalone": "S", "variants": ["V"]}')
    history = [ChatMessage(role="user", content="earlier question")]
    assert await rewrite_query(llm, "it?", history) == ["S", "V"]
    assert "earlier question" in llm.calls[0][1].content


async def test_rewrite_llm_failure_falls_back() -> None:
    llm = _FakeLLM(RuntimeError("provider down"))
    assert await rewrite_query(llm, "raw question", []) == ["raw question"]
