"""DESCRIBE step: figures are stored, described, capped, and never fail an upload."""

import asyncio

import pytest
from eagleeye_core.config import get_settings
from ingest_worker import figures
from ingest_worker.chunking import chunk
from ingest_worker.parsing.base import ParsedDocument, ParsedElement


class Store:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)


def _figure(caption: str = "Figure", labels: str = "2025 · 15.1 · 2026 · 17.6") -> ParsedElement:
    return ParsedElement(caption, page=1, kind="image", image_png=b"png", labels=labels)


def _doc(*elements: ParsedElement) -> ParsedDocument:
    return ParsedDocument(tuple(elements), page_count=1, parser="docling")


@pytest.fixture
def vision(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []

    async def fake(png: bytes, caption: str, labels: str, s: object) -> str:
        calls.append((caption, labels))
        return "Line chart of U.S. LNG exports: 15.1 Bcf/d in 2025, 17.6 Bcf/d forecast for 2026."

    monkeypatch.setattr(figures, "describe_image", fake)
    return calls


def test_a_figure_is_stored_and_described_with_its_caption_and_printed_words(vision) -> None:  # noqa: ANN001
    store = Store()
    doc = _doc(ParsedElement("Intro text."), _figure("Figure 3. LNG exports"))
    out = asyncio.run(figures.describe(doc, store, "personal/d1"))
    fig = out.elements[1]
    assert store.objects == {"personal/d1/figures/000.png": (b"png", "image/png")}
    assert fig.asset_key == "personal/d1/figures/000.png" and fig.image_png is None
    assert fig.text.startswith("Figure 3. LNG exports\n\nLine chart of U.S. LNG exports")
    assert fig.text.endswith("Printed in the figure: 2025 · 15.1 · 2026 · 17.6")
    assert vision == [("Figure 3. LNG exports", "2025 · 15.1 · 2026 · 17.6")]
    assert out.elements[0].text == "Intro text."


def test_a_failed_description_keeps_the_printed_words(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*a: object) -> str:
        return ""

    monkeypatch.setattr(figures, "describe_image", broken)
    out = asyncio.run(figures.describe(_doc(_figure()), Store(), "p"))
    assert out.elements[0].text == "Printed in the figure: 2025 · 15.1 · 2026 · 17.6"
    assert out.elements[0].asset_key == "p/figures/000.png"


def test_figures_past_the_cap_become_their_words(vision, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(get_settings(), "figure_max_per_doc", 1)
    store = Store()
    out = asyncio.run(
        figures.describe(_doc(_figure(), _figure(labels="Q1 · Q2"), _figure(labels="")), store, "p")
    )
    assert list(store.objects) == ["p/figures/000.png"]
    assert [(e.kind, e.text) for e in out.elements[1:]] == [("text", "Q1 · Q2")]  # wordless: gone


def test_a_figure_is_its_own_chunk_with_its_stored_picture() -> None:
    elements = [
        ParsedElement("Exports", heading_level=1),
        ParsedElement("Short paragraph.", page=1),
        ParsedElement("Line chart of LNG exports.", page=1, kind="image", asset_key="p/f/000.png"),
    ]
    chunks = chunk(elements)
    (fig,) = [c for c in chunks if c.element_type == "image"]
    assert fig.content == "Line chart of LNG exports." and fig.asset_key == "p/f/000.png"
    assert fig.heading_path == ("Exports",)
    assert all(c.asset_key is None for c in chunks if c is not fig)
