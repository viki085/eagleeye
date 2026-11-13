"""Bar charts: categories (top N + Other), stacked by a color column, or grouped side by side
when several measures are compared (e.g. revenue vs target per month)."""

from collections import defaultdict
from typing import Any

from eagleeye_charts.aggregate import Resolved, label, month_labels
from eagleeye_charts.intent import DEFAULT_TOP_N, Chart, ChartIntent
from eagleeye_charts.spec import (
    MAX_EVIDENCE_VALUES,
    OTHER,
    Row,
    cap_series,
    fmt,
    make_spec,
    per_series_extremes,
    series_title,
    y_title,
)

HORIZONTAL_MIN_BARS = 9
HORIZONTAL_MIN_LABEL = 13
ORDERED_HORIZONTAL_MIN_BARS = 25  # months/years read best left → right


def _labeller(xs: list[Any]) -> Any:
    if month_labels(xs):
        return lambda v: v.strftime("%Y-%m") if v != OTHER else OTHER
    return lambda v: str(label(v))


def _top_n(
    rows: list[Row], totals: dict[Any, float], top_n: int, additive: bool, notes: list[str]
) -> tuple[list[Row], dict[Any, float], float | None]:
    if len(totals) <= top_n:
        return rows, totals, None
    keep = set(sorted(totals, key=lambda k: -abs(totals[k]))[:top_n])
    dropped = [x for x in totals if x not in keep]
    other_rows: dict[Any, float] = defaultdict(float)
    for x, s, v in rows:
        if x not in keep:
            other_rows[s] += v
    kept = [row for row in rows if row[0] in keep]
    if not additive:
        notes.append(f"Showing the top {top_n} of {len(totals)} categories.")
        return kept, {x: t for x, t in totals.items() if x in keep}, None
    notes.append(f"{len(dropped)} smaller categories are combined into '{OTHER}'.")
    kept += [(OTHER, s, v) for s, v in other_rows.items()]
    other_total = sum(totals[x] for x in dropped)
    return kept, {**{x: t for x, t in totals.items() if x in keep}, OTHER: other_total}, other_total


def build_bar(rows: list[Row], r: Resolved, intent: ChartIntent) -> Chart:
    additive = r.aggregate in ("sum", "count") and not r.multi
    notes: list[str] = []
    if r.color:
        rows, notes = cap_series(rows, additive)
    first = r.measures[0] if r.multi else None
    totals: dict[Any, float] = defaultdict(float)
    for x, s, v in rows:
        totals[x] += v if first is None or s == first else 0.0  # several: rank by the first
    rows, totals, other_total = _top_n(rows, totals, intent.top_n or DEFAULT_TOP_N, additive, notes)
    ordered = r.kinds[r.x] in ("numeric", "temporal")
    sort = intent.sort or ("x" if ordered else "-y")
    real = [k for k in totals if k != OTHER]
    if sort.lstrip("-") == "y":
        cats = sorted(real, key=lambda k: totals[k], reverse=sort.startswith("-"))
    else:
        cats = sorted(real, reverse=sort.startswith("-"))
    as_text = _labeller(real)
    labels = [as_text(c) for c in cats] + ([OTHER] if other_total is not None else [])
    data = [{"x": as_text(x), "series": s, "y": v} for x, s, v in rows]
    limit = ORDERED_HORIZONTAL_MIN_BARS if ordered else HORIZONTAL_MIN_BARS
    horizontal = len(labels) >= limit or max(map(len, labels)) >= HORIZONTAL_MIN_LABEL
    cat_axis: dict[str, Any] = {"field": "x", "type": "nominal", "sort": labels, "title": r.x}
    if not horizontal:
        cat_axis["axis"] = {"labelAngle": 0 if len(labels) <= 12 else -45}
    val_axis = {"field": "y", "type": "quantitative", "title": y_title(r)}
    enc: dict[str, Any] = (
        {"y": cat_axis, "x": val_axis} if horizontal else {"x": cat_axis, "y": val_axis}
    )
    if r.color or r.multi:
        enc["color"] = {"field": "series", "type": "nominal", "title": series_title(r)}
    if r.multi:  # side by side, never stacked: revenue + target is not a total
        enc["yOffset" if horizontal else "xOffset"] = {"field": "series"}
    summary = _summary(rows, r, totals, labels, other_total, as_text)
    summary = " ".join([summary, *notes])
    values = [*totals.values(), *(d["y"] for d in data)]
    if r.aggregate in ("sum", "count") and not r.multi:
        values.append(sum(totals.values()))  # the summary quotes the total
    if r.multi:
        for m in r.measures:
            values.append(sum(v for _, s, v in rows if s == m))
    height = min(560, max(160, 26 * len(labels) * (len(r.measures) if r.multi else 1)))
    mark = {"type": "bar", "tooltip": True, "cornerRadiusEnd": 3}
    return Chart(
        make_spec(intent, summary, data, mark, enc, height if horizontal else 280),
        summary,
        tuple(values[:MAX_EVIDENCE_VALUES]),
        tuple(notes),
    )


def _summary(
    rows: list[Row],
    r: Resolved,
    totals: dict[Any, float],
    labels: list[str],
    other_total: float | None,
    as_text: Any,
) -> str:
    if r.multi:
        return f"{', '.join(r.measures)} by {r.x}: {len(labels)} groups. " + per_series_extremes(
            rows, as_text
        )
    real = {k: v for k, v in totals.items() if k != OTHER}
    hi, lo = max(real, key=lambda k: real[k]), min(real, key=lambda k: real[k])
    text = (
        f"{y_title(r)} by {r.x}: {len(labels)} bars. Highest: {as_text(hi)} ({fmt(real[hi])}); "
        f"lowest: {as_text(lo)} ({fmt(real[lo])})."
    )
    if r.aggregate in ("sum", "count"):
        text += f" Total: {fmt(sum(real.values()) + (other_total or 0.0))}."
    return text
