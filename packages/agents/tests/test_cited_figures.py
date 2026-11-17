"""Cited figures are shown to the answer model as pictures (multimodal plan, Phase 4)."""

import asyncio
import base64

from eagleeye_agents.nodes.answer import MAX_FIGURES, cited_figures, conversation
from eagleeye_llm.litellm_adapter import to_wire
from eagleeye_retrieval.types import RetrievedChunk
from fakes import FakeLLM, make_ctx


def _fig(n: int, key: str | None) -> RetrievedChunk:
    return RetrievedChunk(
        f"c{n}", "d1", "Deck", "personal", n, 2, (), "Line chart.", 0.5, "image", key
    )


def test_figures_are_attached_with_their_source_numbers() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    loaded: list[str] = []

    async def loader(key: str) -> bytes:
        loaded.append(key)
        if key == "broken":
            raise OSError("gone")
        return b"png:" + key.encode()

    ctx.figure_loader = loader
    numbered = [(1, _fig(1, None)), (2, _fig(2, "k2")), (3, _fig(3, "broken")), (4, _fig(4, "k4"))]
    figures = asyncio.run(cited_figures(ctx, numbered))
    assert [n for n, _ in figures] == [2, 4]  # text chunk skipped, broken figure skipped
    assert figures[0][1] == "data:image/png;base64," + base64.b64encode(b"png:k2").decode()

    messages = conversation({"question": "What does the chart show?"}, "system", figures)
    user = messages[-1]
    assert user.images == tuple(url for _, url in figures)
    assert user.content.endswith("(Attached in order: the figures of sources [2], [4].)")


def test_at_most_a_few_figures_and_none_without_a_loader() -> None:
    ctx, _, _ = make_ctx(FakeLLM())
    numbered = [(n, _fig(n, f"k{n}")) for n in range(1, 8)]
    assert asyncio.run(cited_figures(ctx, numbered)) == ()  # no loader configured

    async def loader(key: str) -> bytes:
        return b"png"

    ctx.figure_loader = loader
    assert len(asyncio.run(cited_figures(ctx, numbered))) == MAX_FIGURES


def test_images_go_on_the_wire_as_low_detail_content_parts() -> None:
    (msg,) = to_wire(conversation({"question": "Q"}, "s", ((1, "data:image/png;base64,AA"),))[1:])
    assert msg["content"][0] == {
        "type": "text",
        "text": "Q\n\n(Attached in order: the figures of sources [1].)",
    }
    assert msg["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AA", "detail": "low"},
    }
    (plain,) = to_wire(conversation({"question": "Q"}, "s")[1:])
    assert plain["content"] == "Q"
