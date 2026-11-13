"""Shared pieces of a chart spec: number formatting, safety check, series capping."""

from collections import defaultdict
from typing import Any

from eagleeye_charts.aggregate import Resolved
from eagleeye_charts.intent import MAX_SERIES, ChartError, ChartIntent

OTHER = "Other"
MAX_EVIDENCE_VALUES = 500
FORBIDDEN_KEYS = frozenset({"expr", "transform", "signal", "params", "url", "href", "datasets"})
Row = tuple[Any, Any, float]


def fmt(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"


def assert_safe(node: Any) -> None:
    """Defence in depth: nothing executable or remote may appear anywhere in a spec."""
    if isinstance(node, dict):
        bad = FORBIDDEN_KEYS & node.keys()
        if bad:
            raise ChartError(f"Chart spec contains a forbidden key: {sorted(bad)[0]}.")
        for value in node.values():
            assert_safe(value)
    elif isinstance(node, list):
        for value in node:
            assert_safe(value)


def y_title(r: Resolved) -> str:
    if r.aggregate == "count":
        return "count"
    if r.multi:
        return "value" if r.aggregate == "sum" else f"{r.aggregate} value"
    return f"{r.aggregate} of {r.y}"


def series_title(r: Resolved) -> str:
    return "measure" if r.multi else (r.color or "")


def make_spec(
    intent: ChartIntent, summary: str, data: list[dict], mark: dict, enc: dict, height: int
) -> dict[str, Any]:
    spec = {
        "description": f"{intent.title}. {summary}",
        "data": {"values": data},
        "mark": mark,
        "encoding": enc,
        "width": "container",
        "height": height,
    }
    assert_safe(spec)
    return spec


def cap_series(rows: list[Row], additive: bool) -> tuple[list[Row], list[str]]:
    """≤ MAX_SERIES series: the smallest fold into 'Other' (additive) or are dropped."""
    totals: dict[Any, float] = defaultdict(float)
    for _, s, v in rows:
        totals[s] += abs(v)
    if len(totals) <= MAX_SERIES:
        return rows, []
    keep_n = MAX_SERIES - 1 if additive else MAX_SERIES
    keep = set(sorted(totals, key=lambda s: -totals[s])[:keep_n])
    if not additive:
        note = f"Showing the {keep_n} largest of {len(totals)} series."
        return [r for r in rows if r[1] in keep], [note]
    folded: dict[Any, float] = defaultdict(float)
    kept: list[Row] = []
    for x, s, v in rows:
        if s in keep:
            kept.append((x, s, v))
        else:
            folded[x] += v
    note = f"{len(totals) - keep_n} smaller series are combined into '{OTHER}'."
    return kept + [(x, OTHER, v) for x, v in folded.items()], [note]


def per_series_extremes(rows: list[Row], label_of: Any) -> str:
    """'revenue: highest 2026-10 (2.47M)…' for each series, in first-seen order."""
    by: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        by[row[1]].append(row)
    parts = []
    for name, points in by.items():
        hi, lo = max(points, key=lambda p: p[2]), min(points, key=lambda p: p[2])
        parts.append(
            f"{name}: highest {label_of(hi[0])} ({fmt(hi[2])}), lowest {label_of(lo[0])} "
            f"({fmt(lo[2])}), total {fmt(sum(p[2] for p in points))}"
        )
    return "; ".join(parts) + "."
