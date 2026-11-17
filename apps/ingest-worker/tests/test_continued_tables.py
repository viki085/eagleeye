"""A table that runs onto the next page gets the first part's header (service agreements)."""

from ingest_worker.parsing.base import ParsedElement
from ingest_worker.parsing.docling_pdf import _continued_tables

HEAD = "| Origin | Destination | Type | Rate |\n| --- | --- | --- | --- |"
PART1 = ParsedElement(
    f"{HEAD}\n| Santos | Shanghai | 20DV | 1,262 |",
    page=1,
    kind="table",
    table_html="<table><tbody><tr><th>Origin</th><th>Destination</th><th>Type</th><th>Rate</th></tr>"
    "<tr><td>Santos</td><td>Shanghai</td><td>20DV</td><td>1,262</td></tr></tbody></table>",
)
PART2 = ParsedElement(
    "| Ningbo | Montevideo | 40HC | 5,227 |\n| --- | --- | --- | --- |\n"
    "| Ningbo | Montevideo | 40RF | 9,414 |",
    page=2,
    kind="table",
    table_html="<table><thead><tr><th>Ningbo</th><th>Montevideo</th><th>40HC</th><th>5,227</th></tr>"
    "</thead><tbody><tr><td>Ningbo</td><td>Montevideo</td><td>40RF</td><td>9,414</td></tr></tbody></table>",
)


def test_continuation_gets_the_header_and_keeps_its_first_row() -> None:
    out = _continued_tables([PART1, PART2])
    assert out[0] == PART1
    assert out[1].page == 2
    assert out[1].text == (
        f"{HEAD}\n| Ningbo | Montevideo | 40HC | 5,227 |\n| Ningbo | Montevideo | 40RF | 9,414 |"
    )
    html = out[1].table_html or ""
    assert html.startswith("<table><tbody><tr><th>Origin</th>")
    assert "<td>5,227</td>" in html and "<th>Ningbo</th>" not in html


def test_unrelated_tables_are_left_alone() -> None:
    text = ParsedElement("A paragraph.", page=1, kind="text")
    narrow = ParsedElement("| A | B |\n| --- | --- |\n| 1 | 2 |", page=2, kind="table")
    same_page = ParsedElement(PART2.text, page=1, kind="table")
    later = ParsedElement(PART2.text, page=3, kind="table")
    repeated = ParsedElement(f"{HEAD}\n| x | y | z | 1 |", page=2, kind="table")
    for second in (narrow, same_page, later, repeated):
        assert _continued_tables([PART1, second])[1] == second
    assert _continued_tables([PART1, text, PART2])[2] == PART2
