"""CSV/TSV/XLSX bytes → typed Parquet (C6 §2). Trusted code reading untrusted files.

Nothing here executes file content: CSV is parsed by DuckDB's reader, workbooks are opened
values-only (formulas and macros are never evaluated).
"""

import io
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from eagleeye_datasets.models import MAX_SHEETS, Converted, DatasetError, Limits
from eagleeye_datasets.names import quote, safe_names

MAX_UNZIPPED_BYTES = 400 * 1024 * 1024  # workbook zip-bomb guard
BINARY_PROBE_BYTES = 4096


def _decode(data: bytes) -> str:
    if b"\x00" in data[:BINARY_PROBE_BYTES]:
        raise DatasetError("This doesn't look like a text file. Upload a CSV, TSV or .xlsx.")
    try:
        return data.decode("utf-8-sig")  # also strips a BOM
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _sql_path(path: Path) -> str:
    return "'" + path.as_posix().replace("'", "''") + "'"


def describe(con: duckdb.DuckDBPyConnection, relation: str) -> tuple[dict[str, str], ...]:
    rows = con.execute(f"DESCRIBE {relation}").fetchall()  # noqa: S608 — our own relation name
    return tuple({"name": r[0], "type": r[1]} for r in rows)


def _check_limits(rows: int, columns: int, limits: Limits) -> None:
    if columns == 0 or rows == 0:
        raise DatasetError("The file has no data rows.")
    if columns > limits.max_columns:
        raise DatasetError(f"Too many columns ({columns}); the limit is {limits.max_columns}.")
    if rows > limits.max_rows:
        raise DatasetError(f"Too many rows ({rows:,}); the limit is {limits.max_rows:,}.")


def convert_csv(data: bytes, limits: Limits | None = None) -> Converted:
    limits = limits or Limits()
    text = _decode(data)
    with tempfile.TemporaryDirectory() as tmp:
        src, out = Path(tmp) / "input.csv", Path(tmp) / "data.parquet"
        src.write_text(text, encoding="utf-8", newline="")
        con = duckdb.connect(":memory:")
        try:
            con.execute(
                "CREATE TABLE raw AS SELECT * FROM read_csv(?, sample_size=-1, null_padding=true)",
                [str(src)],
            )
            original = [c["name"] for c in describe(con, "raw")]
            rows = con.execute("SELECT COUNT(*) FROM raw").fetchone()[0]
            _check_limits(rows, len(original), limits)
            names, column_map = safe_names(original)
            select = ", ".join(
                f"{quote(o)} AS {quote(n)}" for o, n in zip(original, names, strict=True)
            )
            con.execute(f"CREATE TABLE clean AS SELECT {select} FROM raw")  # noqa: S608
            con.execute(f"COPY clean TO {_sql_path(out)} (FORMAT parquet, COMPRESSION zstd)")
            columns = describe(con, "clean")
        except duckdb.Error as exc:
            first_line = str(exc).splitlines()[0][:200]
            raise DatasetError(f"The file could not be read as CSV: {first_line}") from exc
        finally:
            con.close()
        return Converted("", out.read_bytes(), columns, column_map, rows)


def _column(values: list[Any]) -> pa.Array:
    try:
        array = pa.array(values)
    except (pa.ArrowInvalid, pa.ArrowTypeError):
        # mixed types in one column: keep every value, as text
        return pa.array([None if v is None else str(v) for v in values], pa.string())
    return array.cast(pa.string()) if pa.types.is_null(array.type) else array


def _sheet_rows(ws: Any, limits: Limits) -> tuple[list[Any], list[tuple[Any, ...]]]:
    header: list[Any] | None = None
    rows: list[tuple[Any, ...]] = []
    for raw in ws.iter_rows(values_only=True):
        if all(v is None or v == "" for v in raw):
            continue
        if header is None:
            cells = list(raw)
            while cells and cells[-1] in (None, ""):
                cells.pop()
            header = cells
            continue
        rows.append(tuple(raw[: len(header)]) + (None,) * max(0, len(header) - len(raw)))
        if len(rows) > limits.max_rows:
            break
    return header or [], rows


def _convert_sheet(ws: Any, limits: Limits) -> Converted | None:
    header, rows = _sheet_rows(ws, limits)
    if not header or not rows:
        return None
    _check_limits(len(rows), len(header), limits)
    names, column_map = safe_names(header)
    table = pa.table({n: _column([r[i] for r in rows]) for i, n in enumerate(names)})
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.parquet"
        path.write_bytes(buf.getvalue())
        con = duckdb.connect(":memory:")
        try:
            # our own temp path, quoted by _sql_path; no user text reaches this SQL
            columns = describe(con, f"SELECT * FROM read_parquet({_sql_path(path)})")  # noqa: S608
        finally:
            con.close()
    return Converted(str(ws.title), buf.getvalue(), columns, column_map, len(rows))


def convert_xlsx(data: bytes, limits: Limits | None = None) -> list[Converted]:
    from openpyxl import load_workbook

    limits = limits or Limits()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            unzipped = sum(info.file_size for info in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise DatasetError("This is not a valid .xlsx workbook.") from exc
    if unzipped > MAX_UNZIPPED_BYTES:
        raise DatasetError("The workbook is too large once unpacked.")
    try:
        # read_only: streaming; data_only: cached values, never formulas; macros are ignored
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types on malformed files
        raise DatasetError("The workbook could not be opened.") from exc
    sheets: list[Converted] = []
    try:
        for ws in workbook.worksheets:
            if len(sheets) >= MAX_SHEETS:
                break
            converted = _convert_sheet(ws, limits)
            if converted is not None:
                sheets.append(converted)
    finally:
        workbook.close()
    if not sheets:
        raise DatasetError("The workbook has no sheet with a header row and data.")
    return sheets
