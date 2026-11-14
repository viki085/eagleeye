"""Data for a chart, computed with DuckDB from the artifact's Parquet (trusted code).

Column names are checked against the table's schema and quoted before they reach SQL;
the model never supplies SQL, values or expressions here.
"""

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import duckdb
import pyarrow.parquet as pq
from eagleeye_datasets.names import quote
from eagleeye_datasets.profile import kind_of

from eagleeye_charts.intent import (
    HISTOGRAM_BINS,
    MAX_MEASURES,
    ChartError,
    ChartIntent,
)

_AGG_SQL = {
    "sum": "SUM({y})",
    "mean": "AVG({y})",
    "median": "MEDIAN({y})",
    "min": "MIN({y})",
    "max": "MAX({y})",
}


ISO_TEXT_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
ISO_PROBE_ROWS = 1000


@dataclass(frozen=True)
class Resolved:
    x: str
    y: str | None  # the first (or only) measure
    color: str | None
    kinds: dict[str, str]  # column -> numeric | temporal | boolean | text
    aggregate: str
    measures: tuple[str, ...] = ()  # ≥ 2 → one series per measure (no color column)
    x_sql: str = ""  # expression for x; text months/dates are cast to DATE
    size: str | None = None  # scatter: numeric column for bubble size
    label: str | None = None  # scatter: column naming each point

    @property
    def multi(self) -> bool:
        return len(self.measures) > 1

    @property
    def x_expr(self) -> str:
        return self.x_sql or quote(self.x)


def iso_text_columns(con: duckdb.DuckDBPyConnection, columns: list[dict[str, str]]) -> set[str]:
    """Text columns whose values are all 'YYYY-MM' or 'YYYY-MM-DD' (e.g. a CSV month column)."""
    found = set()
    for c in columns:
        if kind_of(c["type"]) != "text":
            continue
        col = quote(c["name"])
        values = con.execute(
            f"SELECT DISTINCT {col}::VARCHAR FROM t WHERE {col} IS NOT NULL "  # noqa: S608
            f"LIMIT {ISO_PROBE_ROWS}"
        ).fetchall()
        if values and all(ISO_TEXT_DATE.match(v[0].strip()) for v in values):
            found.add(c["name"])
    return found


def numeric_text_columns(con: duckdb.DuckDBPyConnection, columns: list[dict[str, str]]) -> set[str]:
    """Text columns whose every value parses as a number (e.g. '2100000' after a join)."""
    found = set()
    for c in columns:
        if kind_of(c["type"]) != "text":
            continue
        col = quote(c["name"])
        present, numeric = con.execute(
            f"SELECT COUNT({col}), COUNT(TRY_CAST({col} AS DOUBLE)) FROM t"  # noqa: S608
        ).fetchone()
        if present and present == numeric:
            found.add(c["name"])
    return found


def as_date_sql(name: str) -> str:
    col = f"TRIM({quote(name)}::VARCHAR)"
    return f"TRY_CAST(CASE WHEN LENGTH({col}) = 7 THEN {col} || '-01' ELSE {col} END AS DATE)"


def _find(name: str, columns: list[dict[str, str]]) -> str:
    for c in columns:
        if c["name"].lower() == name.strip().lower():
            return c["name"]
    available = ", ".join(c["name"] for c in columns)
    raise ChartError(f"Unknown column '{name}'. Available columns: {available}.")


def resolve(
    columns: list[dict[str, str]],
    intent: ChartIntent,
    iso_text: set[str] | None = None,
    numeric_text: set[str] | None = None,
) -> Resolved:
    kinds = {c["name"]: kind_of(c["type"]) for c in columns}
    kinds.update({name: "numeric" for name in numeric_text or set()})
    x = _find(intent.x, columns)
    x_sql = ""
    if x in (iso_text or set()):
        kinds[x], x_sql = "temporal", as_date_sql(x)
    raw_y = [intent.y] if isinstance(intent.y, str) else list(intent.y or [])
    if len(raw_y) > MAX_MEASURES:
        raise ChartError(f"At most {MAX_MEASURES} y columns can be compared in one chart.")
    measures = tuple(dict.fromkeys(_find(name, columns) for name in raw_y))
    y = measures[0] if measures else None
    color = _find(intent.color, columns) if intent.color else None
    if len(measures) > 1 and color:
        raise ChartError("Use either several y columns or a color column, not both.")
    size, point_label = _scatter_extras(columns, kinds, intent)
    if len(measures) > 1 and intent.type in ("scatter", "histogram"):
        raise ChartError(f"A {intent.type} takes a single y column.")
    aggregate = intent.aggregate or ("sum" if y else "count")
    if y is None and aggregate != "count":
        raise ChartError(f"aggregate '{aggregate}' needs a y column.")
    for m in measures:
        if aggregate != "count" and kinds[m] != "numeric":
            raise ChartError(f"y column '{m}' is {kinds[m]}, not numeric. Pick a numeric column.")
    if intent.type in ("scatter", "histogram") and kinds[x] != "numeric":
        raise ChartError(f"A {intent.type} needs a numeric x; '{x}' is {kinds[x]}.")
    if intent.type == "scatter" and y is None:
        raise ChartError("A scatter chart needs both x and y numeric columns.")
    if intent.type in ("line", "area") and kinds[x] not in ("numeric", "temporal"):
        raise ChartError(
            f"A {intent.type} chart needs a date or numeric x; '{x}' is {kinds[x]}. "
            "Use a bar chart."
        )
    return Resolved(x, y, color, kinds, aggregate, measures, x_sql, size, point_label)


def _scatter_extras(
    columns: list[dict[str, str]], kinds: dict[str, str], intent: ChartIntent
) -> tuple[str | None, str | None]:
    """The bubble size and point label columns, which only a scatter takes."""
    for option in ("size", "label"):
        if getattr(intent, option) and intent.type != "scatter":
            raise ChartError(f"'{option}' is only for scatter charts.")
    size = _find(intent.size, columns) if intent.size else None
    if size and kinds[size] != "numeric":
        raise ChartError(f"size column '{size}' is {kinds[size]}, not numeric.")
    return size, (_find(intent.label, columns) if intent.label else None)


def open_table(parquet: bytes) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.register("t", pq.read_table(io.BytesIO(parquet)))
    return con


def label(value: Any) -> Any:
    """Axis value → JSON: dates as ISO text (date-only when there is no time part)."""
    if isinstance(value, datetime):
        iso = value.isoformat()
        return iso[:10] if iso[11:19] == "00:00:00" else iso
    if isinstance(value, date):
        return value.isoformat()
    return value


def _value_sql(r: Resolved, measure: str | None) -> str:
    if r.aggregate == "count":
        return "COUNT(*)"
    return _AGG_SQL[r.aggregate].format(y=f"TRY_CAST({quote(measure or '')} AS DOUBLE)")


def grouped(con: duckdb.DuckDBPyConnection, r: Resolved) -> list[tuple[Any, Any, float]]:
    """(x, series or None, value) per group, x not null, value not null. With several
    measures, the series is the measure's column name."""
    x = r.x_expr
    rows: list[tuple[Any, Any, float]] = []
    for measure in r.measures if r.multi else (r.y,):
        value = _value_sql(r, measure)
        if r.multi:
            fetched = con.execute(
                f"SELECT {x} AS x, {value} AS value FROM t WHERE {x} IS NOT NULL "  # noqa: S608
                f"GROUP BY 1 HAVING {value} IS NOT NULL ORDER BY 1"
            ).fetchall()
            rows += [(v[0], measure, float(v[1])) for v in fetched]
            continue
        series = f"{quote(r.color)}::VARCHAR" if r.color else "NULL"
        fetched = con.execute(
            f"SELECT {x} AS x, {series} AS series, {value} AS value FROM t "  # noqa: S608
            f"WHERE {x} IS NOT NULL GROUP BY 1, 2 HAVING {value} IS NOT NULL ORDER BY 1, 2"
        ).fetchall()
        rows += [(v[0], v[1], float(v[2])) for v in fetched]
    return rows


def month_labels(values: list[Any]) -> bool:
    """All values are first-of-month dates with no time → label them 'YYYY-MM'."""
    if not values:
        return False
    for v in values:
        if not isinstance(v, date) or v.day != 1:
            return False
        if isinstance(v, datetime) and (v.hour or v.minute or v.second):
            return False
    return True


def histogram(con: duckdb.DuckDBPyConnection, r: Resolved) -> list[tuple[float, float, int]]:
    """(bin start, bin end, count) for HISTOGRAM_BINS equal-width bins."""
    x = f"{quote(r.x)}::DOUBLE"
    lo, hi = con.execute(f"SELECT MIN({x}), MAX({x}) FROM t").fetchone()  # noqa: S608
    if lo is None:
        raise ChartError(f"Column '{r.x}' has no values.")
    if hi == lo:
        count = con.execute(f"SELECT COUNT({x}) FROM t").fetchone()[0]  # noqa: S608
        return [(float(lo), float(lo), count)]
    width = (hi - lo) / HISTOGRAM_BINS
    rows = con.execute(
        f"SELECT LEAST(FLOOR(({x} - ?) / ?), ?)::INTEGER AS b, COUNT(*) FROM t "  # noqa: S608
        f"WHERE {x} IS NOT NULL GROUP BY 1 ORDER BY 1",
        [lo, width, HISTOGRAM_BINS - 1],
    ).fetchall()
    counts = dict(rows)
    return [(lo + i * width, lo + (i + 1) * width, counts.get(i, 0)) for i in range(HISTOGRAM_BINS)]
