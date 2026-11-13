"""Read Parquet artifacts written by the data gateway (owner checks happen in the router)."""

import csv
import io
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from app.services.jsonable import jsonable

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
CSV_MAX_ROWS = 10_000


@dataclass(frozen=True)
class Page:
    columns: list[str]
    rows: list[list[Any]]
    total: int


def read_table(data: bytes) -> pa.Table:
    return pq.read_table(io.BytesIO(data))


def page(table: pa.Table, offset: int, limit: int) -> Page:
    total = table.num_rows
    start = max(0, min(offset, total))
    sliced = table.slice(start, max(0, limit))
    columns = sliced.column_names
    rows = [[jsonable(r[c]) for c in columns] for r in sliced.to_pylist()]
    return Page(columns, rows, total)


def safe_cell(value: Any) -> str:
    """CSV/formula injection: spreadsheet apps execute cells starting with = + - @."""
    text = "" if value is None else str(jsonable(value))
    return f"'{text}" if text.startswith(FORMULA_PREFIXES) else text


def csv_lines(table: pa.Table) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([safe_cell(c) for c in table.column_names])
    yield buf.getvalue()
    for batch in table.slice(0, CSV_MAX_ROWS).to_batches(max_chunksize=1000):
        buf.seek(0)
        buf.truncate()
        for row in batch.to_pylist():
            writer.writerow([safe_cell(row[c]) for c in table.column_names])
        yield buf.getvalue()
