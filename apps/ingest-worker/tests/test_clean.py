"""CLEAN step: watermarks, running headers/footers and page numbers never reach a chunk."""

from ingest_worker.parsing.base import ParsedDocument, ParsedElement
from ingest_worker.parsing.clean import clean

BODY = "Revenue grew strongly this year across all regions and the board approved a dividend."


def _page(n: int, extra: list[ParsedElement] | None = None) -> list[ParsedElement]:
    return [
        ParsedElement("Acme Corp Annual Report", page=n, bbox=(30, 820, 200, 810)),
        ParsedElement(BODY, page=n, bbox=(30, 760, 560, 700)),
        ParsedElement(f"Page {n}", page=n, bbox=(30, 20, 60, 10)),
        *(extra or []),
    ]


def test_running_headers_and_page_numbers_are_removed() -> None:
    elements = [el for n in range(1, 5) for el in _page(n)]
    out = clean(ParsedDocument(tuple(elements), page_count=4))
    assert [e.text for e in out.elements] == [BODY] * 4
    assert "Acme Corp Annual Report" in out.removed
    assert any(s.startswith("Page ") for s in out.removed)


def test_numbered_headings_in_the_same_spot_are_kept() -> None:
    elements = [
        ParsedElement(f"Section {n} Revenue", page=n, heading_level=1, bbox=(30, 790, 170, 775))
        for n in range(1, 5)
    ]
    assert clean(ParsedDocument(tuple(elements), page_count=4)).elements == tuple(elements)


def test_a_rotated_watermark_is_removed_even_on_one_page() -> None:
    stamp = ParsedElement("CONFIDENTIAL", page=1, bbox=(177, 593, 532, 238))  # diagonal: square
    out = clean(ParsedDocument((*_page(1), stamp), page_count=1))
    assert "CONFIDENTIAL" not in [e.text for e in out.elements]
    assert out.removed == ("CONFIDENTIAL",)


def test_a_watermark_that_bled_into_a_sentence_is_cut_out() -> None:
    stamp = ParsedElement("DRAFT", page=1, bbox=(150, 600, 450, 300))
    bled = ParsedElement("The board DRAFT approved the plan.", page=1, bbox=(30, 500, 560, 480))
    out = clean(ParsedDocument((stamp, bled), page_count=1))
    assert [e.text for e in out.elements] == ["The board approved the plan."]


def test_wide_large_titles_and_tables_are_kept() -> None:
    title = ParsedElement(
        "Quarterly Results Overview",
        page=1,
        kind="heading",
        heading_level=1,
        bbox=(30, 800, 560, 750),
    )  # tall but wide
    table = ParsedElement(
        "| a | b |\n|---|---|\n| 1 | 2 |", page=1, kind="table", bbox=(30, 700, 200, 600)
    )
    out = clean(ParsedDocument((title, table), page_count=1))
    assert out.elements == (title, table)
    assert out.removed == ()


def test_short_documents_and_position_less_elements_are_untouched() -> None:
    two_pages = [el for n in (1, 2) for el in _page(n)]  # too few pages to call it repeated
    assert len(clean(ParsedDocument(tuple(two_pages), page_count=2)).elements) == 6
    plain = tuple(ParsedElement("Page 1", page=n) for n in range(1, 6))  # pypdf: no bbox
    assert clean(ParsedDocument(plain, page_count=5)).elements == plain


def test_the_parse_report_lists_what_was_removed() -> None:
    elements = [el for n in range(1, 4) for el in _page(n)]
    report = clean(ParsedDocument(tuple(elements), page_count=3, parser="docling")).report()
    assert report["parser"] == "docling"
    assert "Acme Corp Annual Report" in report["removed"]
    assert report["elements"] == 3
