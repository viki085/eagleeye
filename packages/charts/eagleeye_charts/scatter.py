"""Scatter and bubble charts: two numeric columns, optionally a bubble size, a colour (categories
or a numeric gradient) and a name per point, with a least-squares trend line (C6 §5).

Like every chart, the spec is built in code from the data: the trend line's end points, the
correlation and the summary sentence are computed here, and the spec carries no colours (the
theme styles the "trend" mark and the colour ramp).
"""

from typing import Any

import duckdb
from eagleeye_datasets.names import quote

from eagleeye_charts.aggregate import Resolved
from eagleeye_charts.intent import MAX_POINTS, Chart, ChartError, ChartIntent
from eagleeye_charts.spec import assert_safe, fmt

SCATTER_MAX_SERIES = 3  # every colour pair meets in a scatter; only 3 slots stay distinct
LABEL_MAX_POINTS = 40  # beyond this, names overlap; they stay in the tooltip
BUBBLE_AREA = (90, 1400)  # px²: smallest and largest bubble
HEIGHT = 340


def _num(column: str) -> str:
    return f"TRY_CAST({quote(column)} AS DOUBLE)"


def _points(con: duckdb.DuckDBPyConnection, r: Resolved) -> tuple[list[dict[str, Any]], int]:
    """Up to MAX_POINTS rows as {x, y, size?, series?, label?}, plus the full row count."""
    numeric_color = bool(r.color) and r.kinds.get(r.color or "") == "numeric"
    extras = {
        "size": _num(r.size) if r.size else None,
        "series": (_num(r.color) if numeric_color else f"{quote(r.color)}::VARCHAR")
        if r.color
        else None,
        "label": f"{quote(r.label)}::VARCHAR" if r.label else None,
    }
    used = {k: v for k, v in extras.items() if v}
    where = f"{_num(r.x)} IS NOT NULL AND {_num(r.y or '')} IS NOT NULL"
    total = con.execute(f"SELECT COUNT(*) FROM t WHERE {where}").fetchone()[0]  # noqa: S608
    cols = ", ".join([_num(r.x), _num(r.y or ""), *used.values()])
    rows = con.execute(
        f"SELECT {cols} FROM t WHERE {where} "  # noqa: S608
        f"USING SAMPLE reservoir({MAX_POINTS} ROWS) REPEATABLE (42)"
    ).fetchall()
    keys = ["x", "y", *used]
    return [dict(zip(keys, row, strict=True)) for row in rows], total


Fit = tuple[float | None, float, float, float, float]


def _fit(con: duckdb.DuckDBPyConnection, r: Resolved) -> Fit:
    """(r, slope, intercept, min x, max x) over every row, not just the plotted sample."""
    x, y = _num(r.x), _num(r.y or "")
    row = con.execute(
        f"SELECT CORR({y}, {x}), REGR_SLOPE({y}, {x}), REGR_INTERCEPT({y}, {x}), "  # noqa: S608
        f"MIN({x}), MAX({x}) FROM t WHERE {x} IS NOT NULL AND {y} IS NOT NULL"
    ).fetchone()
    corr, slope, intercept, lo, hi = row
    if slope is None or lo is None or hi == lo:
        return corr, 0.0, 0.0, 0.0, 0.0
    return corr, float(slope), float(intercept), float(lo), float(hi)


def _trend_layer(r: Resolved, slope: float, intercept: float, lo: float, hi: float) -> dict:
    ends = [{"x": round(v, 6), "y": round(intercept + slope * v, 6)} for v in (lo, hi)]
    return {
        "name": "trend",
        "data": {"values": ends},
        "mark": {"type": "line", "style": "trend", "strokeDash": [6, 4], "strokeWidth": 1.5},
        "encoding": {
            "x": {"field": "x", "type": "quantitative", "title": r.x},
            "y": {"field": "y", "type": "quantitative", "title": r.y},
        },
    }


def _point_layer(r: Resolved, data: list[dict], use_color: bool) -> dict:
    enc: dict[str, Any] = {
        "x": {"field": "x", "type": "quantitative", "title": r.x, "scale": {"zero": False}},
        "y": {"field": "y", "type": "quantitative", "title": r.y, "scale": {"zero": False}},
    }
    tooltip = [
        {"field": "x", "type": "quantitative", "title": r.x, "format": ",.2f"},
        {"field": "y", "type": "quantitative", "title": r.y, "format": ",.2f"},
    ]
    if r.label:
        tooltip.insert(0, {"field": "label", "type": "nominal", "title": r.label})
    if r.size:
        enc["size"] = {
            "field": "size",
            "type": "quantitative",
            "title": r.size,
            "scale": {"range": list(BUBBLE_AREA), "zero": False},
            "legend": {"tickCount": 3},
        }
        tooltip.append({"field": "size", "type": "quantitative", "title": r.size})
    if use_color:
        numeric = r.kinds.get(r.color or "") == "numeric"
        enc["color"] = {
            "field": "series",
            "type": "quantitative" if numeric else "nominal",
            "title": r.color,
        }
        if numeric:
            enc["color"]["scale"] = {"zero": False}
        tooltip.append(
            {"field": "series", "type": "quantitative" if numeric else "nominal", "title": r.color}
        )
    enc["tooltip"] = tooltip
    sized = bool(r.size) or len(data) <= LABEL_MAX_POINTS
    mark = {"type": "circle", "opacity": 0.8 if sized else 0.55, "size": 140 if sized else 50}
    return {"name": "points", "mark": mark, "encoding": enc}


def _label_layer(r: Resolved) -> dict:
    return {
        "name": "labels",
        "mark": {
            "type": "text",
            "align": "left",
            "baseline": "bottom",
            "dx": 9,
            "dy": -7,
            "fontSize": 11,
            "fontWeight": 500,
        },
        "encoding": {
            "x": {"field": "x", "type": "quantitative"},
            "y": {"field": "y", "type": "quantitative"},
            "text": {"field": "label", "type": "nominal"},
        },
    }


def _describe(
    r: Resolved, data: list[dict], total: int, corr: float | None, slope: float, has_trend: bool
) -> tuple[str, list[float]]:
    summary = f"{r.y} against {r.x}: {total:,} points."
    values: list[float] = [float(total)]
    if corr is not None:
        summary += f" Pearson correlation r = {corr:.2f}."
        values.append(round(corr, 2))
    if has_trend:
        summary += f" Fitted trend: slope {slope:.2f} ({r.y} per unit of {r.x})."
        values.append(round(slope, 2))
    if r.size:
        sized = [d for d in data if d.get("size") is not None]
        if sized:
            big, small = max(sized, key=lambda d: d["size"]), min(sized, key=lambda d: d["size"])
            name = (lambda d: f"{d['label']} ") if r.label else (lambda d: "")
            summary += (
                f" Largest {r.size}: {name(big)}({fmt(big['size'])}); "
                f"smallest: {name(small)}({fmt(small['size'])})."
            )
            values += [float(big["size"]), float(small["size"])]
    return summary, values


def build_scatter(con: duckdb.DuckDBPyConnection, r: Resolved, intent: ChartIntent) -> Chart:
    data, total = _points(con, r)
    if not data:
        raise ChartError("No rows have both x and y values.")
    notes: list[str] = []
    numeric_color = bool(r.color) and r.kinds.get(r.color or "") == "numeric"
    use_color = bool(r.color) and (
        numeric_color or len({d["series"] for d in data}) <= SCATTER_MAX_SERIES
    )
    if r.color and not use_color:
        notes.append(f"'{r.color}' has too many values to colour by; points are shown plain.")
    if total > len(data):
        notes.append(f"Showing a random sample of {len(data):,} of {total:,} points.")
    show_labels = bool(r.label) and len(data) <= LABEL_MAX_POINTS
    if r.label and not show_labels:
        notes.append(f"Too many points to name on the chart; '{r.label}' is in the tooltip.")
    corr, slope, intercept, lo, hi = _fit(con, r)
    has_trend = hi > lo and total >= 3
    layers = [_point_layer(r, data, use_color)]
    if show_labels:
        layers.append(_label_layer(r))
    if has_trend:
        layers.insert(0, _trend_layer(r, slope, intercept, lo, hi))
    summary, values = _describe(r, data, total, corr, slope, has_trend)
    summary = " ".join([summary, *notes])
    spec = {
        "description": f"{intent.title}. {summary}",
        "data": {"values": data},
        "layer": layers,
        "width": "container",
        "height": HEIGHT,
    }
    assert_safe(spec)
    return Chart(spec, summary, tuple(values), tuple(notes))
