"""Heatmap: one measure over two categories."""

import io

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from eagleeye_charts.build import build_chart
from eagleeye_charts.heatmap import MAX_ROWS
from eagleeye_charts.intent import ChartError, ChartIntent

COLS = [
    {"name": "lane", "type": "VARCHAR"},
    {"name": "month", "type": "VARCHAR"},
    {"name": "delay", "type": "DOUBLE"},
]


def parquet(table: dict) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table(table), buf)
    return buf.getvalue()


def delays() -> bytes:
    # two rows per (lane, month): the mean is the cell
    lanes = ["AEU", "AEU", "TAT", "TAT"] * 2
    months = ["2026-01", "2026-02"] * 4
    return parquet(
        {"lane": lanes, "month": months, "delay": [1.0, 2.0, 3.0, 4.0, 3.0, 4.0, 5.0, 6.0]}
    )


def heat(**kw: object):
    args = {"title": "Delay by lane and month", "type": "heatmap", "x": "month", "y": "delay"}
    return build_chart(delays(), COLS, ChartIntent(**{**args, **kw}))


def test_cells_aggregate_and_the_summary_names_the_extremes() -> None:
    chart = heat(color="lane", aggregate="mean")
    spec = chart.spec
    assert spec["mark"]["type"] == "rect"
    assert spec["encoding"]["x"]["sort"] == ["2026-01", "2026-02"]
    assert set(spec["encoding"]["y"]["sort"]) == {"AEU", "TAT"}
    assert spec["encoding"]["color"] == {
        "field": "y",
        "type": "quantitative",
        "title": "mean of delay",
    }
    cells = {(d["series"], d["x"]): d["y"] for d in spec["data"]["values"]}
    assert cells == {
        ("AEU", "2026-01"): 2.0,
        ("AEU", "2026-02"): 3.0,
        ("TAT", "2026-01"): 4.0,
        ("TAT", "2026-02"): 5.0,
    }
    assert "highest 5" in chart.summary and "lowest 2" in chart.summary
    assert "color" not in str(spec["encoding"]["color"].get("scale", ""))  # no colours in the spec


def test_a_heatmap_needs_rows_and_one_measure() -> None:
    with pytest.raises(ChartError, match="color column"):
        heat()
    with pytest.raises(ChartError):
        heat(color="lane", y=["delay", "delay2"])


def test_too_many_rows_keep_the_largest_and_say_so() -> None:
    n = MAX_ROWS + 5
    table = {
        "lane": [f"L{i:02d}" for i in range(n)],
        "month": ["2026-01"] * n,
        "delay": [float(i) for i in range(n)],
    }
    chart = build_chart(
        parquet(table),
        COLS,
        ChartIntent(title="Delays", type="heatmap", x="month", y="delay", color="lane"),
    )
    assert len(chart.spec["encoding"]["y"]["sort"]) == MAX_ROWS
    assert "L00" not in chart.spec["encoding"]["y"]["sort"]  # the smallest are dropped
    assert f"Showing the {MAX_ROWS} largest" in chart.summary
