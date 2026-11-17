"""Rerank: the fast model's order is applied safely; any failure keeps the fused order."""

import asyncio

from eagleeye_llm.gateway import Usage
from eagleeye_retrieval.rerank import parse_ranking, preview, rerank
from eagleeye_retrieval.types import RetrievedChunk


def _chunk(n: int, content: str = "text") -> RetrievedChunk:
    return RetrievedChunk(f"c{n}", "d1", "Outlook", "personal", n, 1, ("Prices",), content, 0.5)


class FakeLLM:
    def __init__(self, reply: str | Exception) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, tier, messages, max_tokens=1024, json_mode=False, temperature=None):  # noqa: ANN001, ANN201
        self.prompts.append(messages[-1].content)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, Usage()


def test_the_models_order_is_applied_and_omitted_passages_keep_their_place() -> None:
    assert parse_ranking('{"ranking": [3, 1]}', 4) == [2, 0, 1, 3]


def test_bad_numbers_and_bad_json_never_lose_a_passage() -> None:
    assert parse_ranking('{"ranking": [9, 0, "2", true, 2, 2]}', 3) == [1, 0, 2]
    assert parse_ranking("not json", 3) == [0, 1, 2]
    assert parse_ranking('```json\n{"ranking": [2]}\n```', 2) == [1, 0]


def test_rerank_reorders_by_the_reply() -> None:
    chunks = [_chunk(0), _chunk(1), _chunk(2, "Retail diesel price $5.25")]
    llm = FakeLLM('{"ranking": [3, 1, 2]}')
    out = asyncio.run(rerank(llm, "diesel price?", chunks))
    assert [c.chunk_id for c in out] == ["c2", "c0", "c1"]
    assert "[3] Outlook › Prices\nRetail diesel price $5.25" in llm.prompts[0]


def test_a_failed_call_keeps_the_fused_order() -> None:
    chunks = [_chunk(0), _chunk(1)]
    out = asyncio.run(rerank(FakeLLM(RuntimeError("503")), "q", chunks))
    assert out == chunks


def test_previews_are_short_and_flattened() -> None:
    text = preview(_chunk(0, "a  b\n\nc " * 500))
    assert text.startswith("Outlook › Prices\na b c") and len(text) < 700
