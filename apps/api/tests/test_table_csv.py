"""A cited table as CSV ("Use as data file")."""

import pytest
from app.services.table_csv import TableParseError, html_rows, markdown_rows, to_csv


def test_html_with_merged_cells_becomes_a_rectangular_grid() -> None:
    html = (
        "<table><tbody><tr><th>Region</th><th colspan='2'>Sales</th></tr>"
        "<tr><td rowspan='2'>North</td><td>1,200</td><td>Q1</td></tr>"
        "<tr><td>1,350</td><td>Q2</td></tr></tbody></table>"
    )
    assert html_rows(html) == [
        ["Region", "Sales", "Sales"],
        ["North", "1,200", "Q1"],
        ["North", "1,350", "Q2"],
    ]


def test_csv_quotes_commas_and_fills_blank_headers() -> None:
    html = "<table><tr><th>Port</th><th></th></tr><tr><td>Rotterdam, NL</td><td>5</td></tr></table>"
    assert to_csv(html, "") == b'Port,column_2\n"Rotterdam, NL",5\n'


def test_markdown_is_used_when_there_is_no_html() -> None:
    md = "| Origin | Rate |\n| --- | --- |\n| Santos | 1,262 |"
    assert markdown_rows(md) == [["Origin", "Rate"], ["Santos", "1,262"]]
    assert to_csv(None, md) == b'Origin,Rate\nSantos,"1,262"\n'


def test_markup_inside_cells_is_kept_as_text_only() -> None:
    html = "<table><tr><th>A</th></tr><tr><td><script>x()</script>&lt;b&gt; ok</td></tr></table>"
    assert to_csv(html, "").decode() == "A\nx()<b> ok\n"


@pytest.mark.parametrize(
    "html, md", [(None, "just text"), ("<table><tr><td>1</td></tr></table>", "")]
)
def test_no_table_is_refused(html: str | None, md: str) -> None:
    with pytest.raises(TableParseError):
        to_csv(html, md)
