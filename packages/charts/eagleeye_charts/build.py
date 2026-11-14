"""Chart intent + artifact data → Vega-Lite spec (C6 §5).

Every plotted number comes from the data; the summary sentence is computed here, so the
model can quote it without inventing figures. Specs carry no colours (the frontend themes
them) and no expressions, transforms, parameters or URLs.
"""

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

from eagleeye_charts.aggregate import (
    Resolved,
    grouped,
    histogram,
    iso_text_columns,
    label,
    numeric_text_columns,
    open_table,
    resolve,
)
from eagleeye_charts.bars import build_bar
from eagleeye_charts.downsample import lttb
from eagleeye_charts.intent import MAX_POINTS, Chart, ChartError, ChartIntent
from eagleeye_charts.scatter import build_scatter
from eagleeye_charts.spec import (
    MAX_EVIDENCE_VALUES,
    OTHER,
    Row,
    assert_safe,
    cap_series,
    fmt,
    make_spec,
    per_series_extremes,
    series_title,
    y_title,
)

__all__ = ["OTHER", "assert_safe", "build_chart"]

POINT_MARK_MAX = 60


def _xnum(value: Any) -> float:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=UTC)).timestamp()
    if isinstance(value, date):
        return float(value.toordinal()) * 86400.0
    return float(value)


def _series(rows: list[Row], r: Resolved, intent: ChartIntent) -> Chart:
    additive = r.aggregate in ("sum", "count") and not r.multi
    rows, notes = cap_series(rows, additive) if r.color else (rows, [])
    by_series: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        by_series[row[1]].append(row)
    per_series = max(3, MAX_POINTS // len(by_series))
    data: list[dict[str, Any]] = []
    for name, points in by_series.items():
        points.sort(key=lambda p: _xnum(p[0]))
        if len(points) > per_series:
            keep = lttb([(_xnum(p[0]), p[2]) for p in points], per_series)
            points = [points[i] for i in keep]
            notes.append("Long series are downsampled to keep their shape.")
        data += [{"x": label(x), "series": name, "y": v} for x, _, v in points]
    notes = list(dict.fromkeys(notes))
    temporal = r.kinds[r.x] == "temporal"
    enc: dict[str, Any] = {
        "x": {"field": "x", "type": "temporal" if temporal else "quantitative", "title": r.x},
        "y": {"field": "y", "type": "quantitative", "title": y_title(r)},
    }
    if r.color or r.multi:
        enc["color"] = {"field": "series", "type": "nominal", "title": series_title(r)}
    if intent.type == "area":
        mark: dict[str, Any] = {"type": "area", "tooltip": True, "line": True, "opacity": 0.35}
        if r.multi:
            enc["y"]["stack"] = None  # overlapping areas, not a misleading stack of measures
    else:
        mark = {"type": "line", "tooltip": True, "point": len(data) <= POINT_MARK_MAX}
    xs = sorted((p[0] for p in rows), key=_xnum)
    span = f"from {label(xs[0])} to {label(xs[-1])}"
    if r.multi:
        summary = f"{', '.join(r.measures)} over {r.x} {span}. " + per_series_extremes(rows, label)
    else:
        hi, lo = max(rows, key=lambda p: p[2]), min(rows, key=lambda p: p[2])
        summary = (
            f"{y_title(r)} over {r.x} {span}{f', {len(by_series)} series' if r.color else ''}. "
            f"Highest: {fmt(hi[2])} at {label(hi[0])}; lowest: {fmt(lo[2])} at {label(lo[0])}."
        )
        if not r.color:
            ordered = sorted(rows, key=lambda p: _xnum(p[0]))
            summary += f" First: {fmt(ordered[0][2])}; last: {fmt(ordered[-1][2])}."
    summary = " ".join([summary, *notes])
    values = tuple(p[2] for p in rows)[:MAX_EVIDENCE_VALUES]
    return Chart(make_spec(intent, summary, data, mark, enc, 280), summary, values, tuple(notes))


def _histogram(con: Any, r: Resolved, intent: ChartIntent) -> Chart:
    bins = histogram(con, r)
    data = [{"x": a, "x2": b, "y": n} for a, b, n in bins]
    enc = {
        "x": {"field": "x", "type": "quantitative", "bin": {"binned": True}, "title": r.x},
        "x2": {"field": "x2"},
        "y": {"field": "y", "type": "quantitative", "title": "count"},
    }
    peak = max(bins, key=lambda b: b[2])
    count = sum(b[2] for b in bins)
    summary = (
        f"Distribution of {r.x}: {count:,} values from {fmt(bins[0][0])} to {fmt(bins[-1][1])}. "
        f"Most common range: {fmt(peak[0])} to {fmt(peak[1])} ({peak[2]:,} values)."
    )
    values = (float(count), float(peak[2]), bins[0][0], bins[-1][1], peak[0], peak[1])
    mark = {"type": "bar", "tooltip": True}
    return Chart(make_spec(intent, summary, data, mark, enc, 280), summary, values)


def build_chart(parquet: bytes, columns: list[dict[str, str]], intent: ChartIntent) -> Chart:
    con = open_table(parquet)
    try:
        r = resolve(
            columns, intent, iso_text_columns(con, columns), numeric_text_columns(con, columns)
        )
        if intent.type == "histogram":
            return _histogram(con, r, intent)
        if intent.type == "scatter":
            return build_scatter(con, r, intent)
        rows = grouped(con, r)
        if not rows:
            raise ChartError("There is no data to plot for these columns.")
        if r.color and len({s for _, s, _ in rows}) <= 1:
            # a single-valued color column adds a legend and nothing else
            r = replace(r, color=None)
            rows = [(x, None, v) for x, _, v in rows]
        return build_bar(rows, r, intent) if intent.type == "bar" else _series(rows, r, intent)
    finally:
        con.close()
