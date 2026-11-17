"""A cited table as CSV, for "Use as data file".

The source is the table's HTML from the PDF parser (whole structure, merged cells included) or,
for tables without it, the chunk's Markdown. Only cell text is kept; nothing is evaluated.
"""

import csv
import io
from html.parser import HTMLParser

MAX_ROWS = 5000
MAX_COLS = 100
MAX_CELL_CHARS = 1000
MAX_SPAN = 50


class TableParseError(ValueError):
    """No usable table (fewer than two rows or one column)."""


def _span(value: str | None) -> int:
    try:
        return max(1, min(int(value or 1), MAX_SPAN))
    except ValueError:
        return 1


class _Grid(HTMLParser):
    """<tr>/<td>/<th> into a rectangular grid; colspan and rowspan repeat the cell's text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._pending: dict[tuple[int, int], str] = {}  # rowspan cells still to place
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._spans = (1, 1)
        self._depth = 0  # nested tables are read as text of the outer cell

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._depth += 1
        if self._depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)
            self._cell, self._spans = [], (_span(a.get("colspan")), _span(a.get("rowspan")))

    def handle_endtag(self, tag: str) -> None:
        if tag == "table":
            self._depth -= 1
        if self._depth != 1 and tag != "table":
            return
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._place(" ".join("".join(self._cell).split())[:MAX_CELL_CHARS])
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._fill_pending()
            if len(self.rows) < MAX_ROWS:
                self.rows.append(self._row[:MAX_COLS])
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def _fill_pending(self) -> None:
        assert self._row is not None
        r = len(self.rows)
        while (r, len(self._row)) in self._pending:
            self._row.append(self._pending.pop((r, len(self._row))))

    def _place(self, text: str) -> None:
        assert self._row is not None
        self._fill_pending()
        cols, rows = self._spans
        r = len(self.rows)
        for _ in range(cols):
            c = len(self._row)
            self._row.append(text)
            for extra in range(1, rows):
                self._pending[(r + extra, c)] = text


def html_rows(html: str) -> list[list[str]]:
    grid = _Grid()
    grid.feed(html)
    grid.close()
    return grid.rows


def markdown_rows(markdown: str) -> list[list[str]]:
    rows = []
    for line in markdown.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip()[:MAX_CELL_CHARS] for c in line.strip("|").split("|")]
        if all(c and set(c) <= set("-: ") for c in cells):
            continue  # the header rule
        rows.append(cells[:MAX_COLS])
    return rows[:MAX_ROWS]


def to_csv(html: str | None, markdown: str) -> bytes:
    """CSV (UTF-8, header first). Prefers the HTML structure; falls back to the Markdown."""
    rows = html_rows(html) if html else []
    if len(rows) < 2:
        rows = markdown_rows(markdown)
    width = max((len(r) for r in rows), default=0)
    if len(rows) < 2 or width < 1:
        raise TableParseError("no table to save")
    header = [h or f"column_{i + 1}" for i, h in enumerate(rows[0] + [""] * (width - len(rows[0])))]
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    for row in rows[1:]:
        writer.writerow(row + [""] * (width - len(row)))
    return buf.getvalue().encode("utf-8")
