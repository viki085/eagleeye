"""Automatic profile of a Parquet dataset (C6 §2.3), computed with DuckDB.

The profile is what "run EDA on my file" reads first: per-column statistics, data-quality
warnings, the strongest correlations and a masked sample. Column names come from
`names.safe_names`, so they are safe to quote into the statistics queries.
"""

import tempfile
from pathlib import Path
from typing import Any

import duckdb
from eagleeye_core.pii import MASK, looks_personal, pii_column_name

from eagleeye_datasets.names import quote
from eagleeye_datasets.values import clip, jsonable, round_sig

SAMPLE_ROWS = 20
TOP_VALUES = 5
TOP_VALUES_MAX_DISTINCT = 20
MAX_CORRELATION_COLUMNS = 20
MAX_CORRELATIONS = 10
MIN_CORRELATION = 0.3
ID_LIKE_MIN_ROWS = 20
MOSTLY_NULL_PCT = 50.0
NUMERIC_TEXT_SHARE = 0.8
PII_PROBE_ROWS = 50
_INTEGERS = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT")
_NUMERIC = (*_INTEGERS, "UINTEGER", "UBIGINT", "UHUGEINT", "FLOAT", "DOUBLE")


def kind_of(type_name: str) -> str:
    t = type_name.upper()
    if t in _NUMERIC or t.startswith("DECIMAL"):
        return "numeric"
    if t == "BOOLEAN":
        return "boolean"
    if t.startswith(("DATE", "TIMESTAMP", "TIME")):
        return "temporal"
    return "text"


def _num(value: Any) -> Any:
    return round_sig(jsonable(value))


def _numeric_stats(con: duckdb.DuckDBPyConnection, col: str) -> dict[str, Any]:
    c = f"{col}::DOUBLE"
    lo, hi, mean, median, std, q25, q75 = con.execute(
        f"SELECT MIN({c}), MAX({c}), AVG({c}), MEDIAN({c}), STDDEV_SAMP({c}), "  # noqa: S608
        f"QUANTILE_CONT({c}, 0.25), QUANTILE_CONT({c}, 0.75) FROM t"
    ).fetchone()
    stats = {"min": lo, "max": hi, "mean": mean, "median": median, "std": std, "q25": q25}
    stats["q75"] = q75
    outliers = 0
    if q25 is not None and q75 is not None and q75 > q25:
        fence = 1.5 * (q75 - q25)
        outliers = con.execute(
            f"SELECT COUNT(*) FROM t WHERE {c} < ? OR {c} > ?",  # noqa: S608
            [q25 - fence, q75 + fence],
        ).fetchone()[0]
    return {**{k: _num(v) for k, v in stats.items()}, "outliers": outliers}


def _text_stats(con: duckdb.DuckDBPyConnection, col: str) -> dict[str, Any]:
    min_len, max_len, numeric = con.execute(
        f"SELECT MIN(LENGTH({col})), MAX(LENGTH({col})), "  # noqa: S608
        f"COUNT(TRY_CAST({col} AS DOUBLE)) FROM t"
    ).fetchone()
    return {"min_len": min_len, "max_len": max_len, "numeric_values": numeric}


def _top_values(con: duckdb.DuckDBPyConnection, col: str) -> list[dict[str, Any]]:
    rows = con.execute(
        f"SELECT {col}, COUNT(*) AS n FROM t WHERE {col} IS NOT NULL "  # noqa: S608
        f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT {TOP_VALUES}"
    ).fetchall()
    return [{"value": clip(jsonable(v), 60), "count": n} for v, n in rows]


def _is_pii(con: duckdb.DuckDBPyConnection, name: str, col: str, kind: str) -> bool:
    if pii_column_name(name):
        return True
    if kind != "text":
        return False
    probe = con.execute(
        f"SELECT {col} FROM t WHERE {col} IS NOT NULL LIMIT {PII_PROBE_ROWS}"  # noqa: S608
    ).fetchall()
    return any(looks_personal(v[0]) for v in probe)


def _column(
    con: duckdb.DuckDBPyConnection, name: str, type_name: str, total: int, original: str
) -> dict[str, Any]:
    col, kind = quote(name), kind_of(type_name)
    nulls, distinct = con.execute(
        f"SELECT COUNT(*) FILTER (WHERE {col} IS NULL), COUNT(DISTINCT {col}) FROM t"  # noqa: S608
    ).fetchone()
    present = total - nulls
    out: dict[str, Any] = {
        "name": name,
        "original": original,
        "type": type_name,
        "kind": kind,
        "null_pct": round(100.0 * nulls / total, 2) if total else 0.0,
        "distinct": distinct,
    }
    flags: list[str] = []
    if kind == "numeric":
        out.update(_numeric_stats(con, col))
    elif kind == "temporal":
        lo, hi = con.execute(f"SELECT MIN({col}), MAX({col}) FROM t").fetchone()  # noqa: S608
        out.update({"min": jsonable(lo), "max": jsonable(hi)})
    elif kind == "text":
        text = _text_stats(con, col)
        numeric = text.pop("numeric_values")
        out.update(text)
        if present and NUMERIC_TEXT_SHARE <= numeric / present < 1:
            flags.append("mixed_types")
    pii = _is_pii(con, name, col, kind)
    if pii:
        flags.append("pii")
    if present and distinct <= 1:
        flags.append("constant")
    integer = type_name.upper() in _INTEGERS or type_name.upper() in ("UINTEGER", "UBIGINT")
    id_like = present >= ID_LIKE_MIN_ROWS and distinct == present and (integer or kind == "text")
    if id_like:
        flags.append("id_like")
    if out["null_pct"] > MOSTLY_NULL_PCT:
        flags.append("mostly_null")
    categorical = kind in ("text", "boolean") or distinct <= TOP_VALUES_MAX_DISTINCT
    if categorical and not pii and not id_like and present:
        out["top"] = _top_values(con, col)
    out["flags"] = flags
    return out


def _correlations(
    con: duckdb.DuckDBPyConnection, columns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    numeric = [
        c["name"]
        for c in columns
        if c["kind"] == "numeric" and not {"constant", "id_like"} & set(c["flags"])
    ][:MAX_CORRELATION_COLUMNS]
    pairs = [(a, b) for i, a in enumerate(numeric) for b in numeric[i + 1 :]]
    if not pairs:
        return []
    exprs = ", ".join(f"CORR({quote(a)}::DOUBLE, {quote(b)}::DOUBLE)" for a, b in pairs)
    values = con.execute(f"SELECT {exprs} FROM t").fetchone()  # noqa: S608
    found = [
        {"a": a, "b": b, "r": round(r, 3)}
        for (a, b), r in zip(pairs, values, strict=True)
        if r is not None and abs(r) >= MIN_CORRELATION
    ]
    return sorted(found, key=lambda x: -abs(x["r"]))[:MAX_CORRELATIONS]


def _sample(con: duckdb.DuckDBPyConnection, columns: list[dict[str, Any]]) -> dict[str, Any]:
    pii = [("pii" in c["flags"]) for c in columns]
    rows = con.execute(f"SELECT * FROM t LIMIT {SAMPLE_ROWS}").fetchall()  # noqa: S608
    masked = [
        [
            None if v is None else MASK if pii[i] or looks_personal(v) else clip(jsonable(v))
            for i, v in enumerate(row)
        ]
        for row in rows
    ]
    return {"columns": [c["name"] for c in columns], "rows": masked}


def _warnings(columns: list[dict[str, Any]], duplicates: int) -> list[str]:
    notes = {
        "mixed_types": "holds mostly numbers but is stored as text (mixed values)",
        "mostly_null": "is more than half empty",
        "constant": "has a single value",
        "pii": "looks like personal data; values are hidden from the assistant",
    }
    out = [f"Column '{c['name']}' {notes[f]}." for c in columns for f in c["flags"] if f in notes]
    if duplicates:
        out.append(f"{duplicates:,} fully duplicated row{'s' if duplicates != 1 else ''}.")
    return out


def profile_parquet(data: bytes, column_map: dict[str, str] | None = None) -> dict[str, Any]:
    column_map = column_map or {}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "data.parquet"
        path.write_bytes(data)
        con = duckdb.connect(":memory:")
        try:
            con.execute("CREATE TABLE t AS SELECT * FROM read_parquet(?)", [str(path)])
            total = con.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            described = con.execute("DESCRIBE t").fetchall()
            columns = [
                _column(con, r[0], r[1], total, column_map.get(r[0], r[0])) for r in described
            ]
            unique = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT * FROM t)").fetchone()[0]
            duplicates = total - unique
            return {
                "row_count": total,
                "column_count": len(columns),
                "duplicate_rows": duplicates,
                "columns": columns,
                "correlations": _correlations(con, columns),
                "warnings": _warnings(columns, duplicates),
                "sample": _sample(con, columns),
            }
        finally:
            con.close()
