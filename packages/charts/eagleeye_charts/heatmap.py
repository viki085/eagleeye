"""Heatmap: one measure over two categories (e.g. average delay by trade lane and month).

x = the columns, color = the rows, y = the measure (aggregated per cell). Cells are shaded on
one sequential hue by the frontend; the spec carries no colours (C6 §5).
"""

from collections import defaultdict
from typing import Any

from eagleeye_charts.aggregate import Resolved, grouped, label, month_labels
from eagleeye_charts.intent import Chart, ChartError, ChartIntent
from eagleeye_charts.spec import MAX_EVIDENCE_VALUES, OTHER, fmt, make_spec, y_title

MAX_COLUMNS = 31  # e.g. days of a month
MAX_ROWS = 20
CELL_PX = 26


def _keep(totals: dict[Any, float], limit: int, ordered: bool) -> list[Any]:
    """The categories to draw: all of them in order when they fit, else the `limit` largest."""
    keys = list(totals)
    if len(keys) > limit:
        keys = sorted(keys, key=lambda k: totals[k], reverse=True)[:limit]
    return sorted(keys) if ordered else sorted(keys, key=lambda k: totals[k], reverse=True)


def build_heatmap(con: Any, r: Resolved, intent: ChartIntent) -> Chart:
    if not r.color:
        raise ChartError("A heatmap needs a color column for the rows (x gives the columns).")
    if r.multi:
        raise ChartError("A heatmap takes a single y column.")
    rows = [(x, s, v) for x, s, v in grouped(con, r) if s is not None]
    if not rows:
        raise ChartError("There is no data to plot for these columns.")
    by_x: dict[Any, float] = defaultdict(float)
    by_row: dict[Any, float] = defaultdict(float)
    for x, s, v in rows:
        by_x[x] += abs(v)
        by_row[s] += abs(v)
    notes = []
    if len(by_x) > MAX_COLUMNS:
        notes.append(f"Showing the {MAX_COLUMNS} largest of {len(by_x)} {r.x} values.")
    if len(by_row) > MAX_ROWS:
        notes.append(f"Showing the {MAX_ROWS} largest of {len(by_row)} {r.color} values.")
    ordered_x = r.kinds[r.x] in ("numeric", "temporal")
    xs = _keep(by_x, MAX_COLUMNS, ordered_x)
    ys = _keep(by_row, MAX_ROWS, False)
    kept_x, kept_y = set(xs), set(ys)
    cells = [(x, s, v) for x, s, v in rows if x in kept_x and s in kept_y]
    # month dates read as "2026-01", as on bar charts
    as_text = (lambda v: v.strftime("%Y-%m")) if month_labels(xs) else (lambda v: str(label(v)))
    data = [{"x": as_text(x), "series": str(s), "y": v} for x, s, v in cells]
    measure = y_title(r)
    enc = {
        "x": {"field": "x", "type": "nominal", "sort": [as_text(x) for x in xs], "title": r.x},
        "y": {"field": "series", "type": "nominal", "sort": [str(s) for s in ys], "title": r.color},
        "color": {"field": "y", "type": "quantitative", "title": measure},
    }
    hi = max(cells, key=lambda c: c[2])
    lo = min(cells, key=lambda c: c[2])
    summary = (
        f"{measure} by {r.x} and {r.color}: highest {fmt(hi[2])} ({r.color} {hi[1]}, "
        f"{r.x} {as_text(hi[0])}); lowest {fmt(lo[2])} ({r.color} {lo[1]}, {r.x} {as_text(lo[0])})."
    )
    if any(d["series"] == OTHER for d in data):
        notes.append(f"'{OTHER}' is a value in the data.")
    summary = " ".join([summary, *notes])
    mark = {"type": "rect", "tooltip": True}
    height = min(620, max(160, CELL_PX * len(ys) + 70))
    return Chart(
        make_spec(intent, summary, data, mark, enc, height),
        summary,
        tuple(v for _, _, v in cells[:MAX_EVIDENCE_VALUES]),
        tuple(notes),
    )
