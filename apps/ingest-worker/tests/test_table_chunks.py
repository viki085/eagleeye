"""Tables are their own chunks; long tables split by rows with the header repeated."""

from ingest_worker.chunking import chunk
from ingest_worker.parsing.base import ParsedElement

TABLE = "| Region | 2024 | 2025 |\n|---|---|---|\n| North | 120 | 150 |\n| South | 90 | 110 |"


def test_a_table_is_one_chunk_and_never_mixed_with_text() -> None:
    elements = [
        ParsedElement("Revenue", heading_level=1),
        ParsedElement("Short intro.", page=1),
        ParsedElement(TABLE, page=1, kind="table", bbox=(1, 2, 3, 4), table_html="<table/>"),
        ParsedElement("Short outro.", page=1),
    ]
    chunks = chunk(elements)
    tables = [c for c in chunks if c.element_type == "table"]
    assert len(tables) == 1
    assert tables[0].content == TABLE
    assert tables[0].heading_path == ("Revenue",)
    assert tables[0].bbox == (1, 2, 3, 4) and tables[0].table_html == "<table/>"
    assert all("Region" not in c.content for c in chunks if c.element_type == "text")
    assert [c.chunk_no for c in chunks] == list(range(len(chunks)))


def test_a_long_table_splits_by_rows_with_the_header_in_every_part() -> None:
    rows = "\n".join(f"| Region {i} | {i * 10} | {i * 11} |" for i in range(200))
    long_table = f"| Region | 2024 | 2025 |\n|---|---|---|\n{rows}"
    chunks = chunk([ParsedElement(long_table, page=3, kind="table")], max_chars=1600)
    assert len(chunks) > 1
    for c in chunks:
        assert c.content.startswith("| Region | 2024 | 2025 |\n|---|---|---|\n")
        assert len(c.content) <= 1600
        assert c.element_type == "table" and c.page == 3
    body_rows = [line for c in chunks for line in c.content.splitlines()[2:]]
    assert len(body_rows) == 200  # every row kept exactly once


def test_text_only_documents_chunk_exactly_as_before() -> None:
    elements = [ParsedElement("Policy", heading_level=1), ParsedElement("Body text. " * 20)]
    (only,) = chunk(elements)
    assert only.element_type == "text" and only.bbox is None and only.table_html is None


def test_text_chunks_get_the_box_around_their_paragraphs_on_the_first_page() -> None:
    elements = [
        ParsedElement("First paragraph. " * 5, page=4, bbox=(72, 700, 300, 650)),
        ParsedElement("Second paragraph. " * 5, page=4, bbox=(60, 640, 520, 600)),
        ParsedElement("Runs onto the next page. " * 3, page=5, bbox=(10, 800, 590, 20)),
    ]
    (only,) = chunk(elements)
    assert only.page == 4
    assert only.bbox == (60, 700, 520, 600)  # page 5's box is left out


def test_union_box_handles_both_origins() -> None:
    from ingest_worker.chunking import union_box

    assert union_box([]) is None
    assert union_box([(10, 100, 50, 120), (5, 130, 60, 150)]) == (5, 100, 60, 150)
