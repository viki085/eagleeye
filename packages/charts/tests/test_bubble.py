"""Bubble scatter: size, label and numeric colour columns, and the fitted trend line."""

import io
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from eagleeye_charts.build import build_chart
from eagleeye_charts.intent import ChartError, ChartIntent
from eagleeye_charts.scatter import LABEL_MAX_POINTS


def parquet(table: dict) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table(table), buf)
    return buf.getvalue()


LANES = ["AEU", "TAT", "IAS", "AMD"]
COLS = [
    {"name": "lane", "type": "VARCHAR"},
    {"name": "on_time", "type": "DOUBLE"},
    {"name": "nps", "type": "DOUBLE"},
    {"name": "claims", "type": "BIGINT"},
    {"name": "delay", "type": "DOUBLE"},
]


def lanes() -> bytes:
    return parquet(
        {
            "lane": LANES,
            "on_time": [70.0, 80.0, 60.0, 90.0],
            "nps": [10.0, 20.0, 0.0, 30.0],  # nps = on_time - 60: a perfect fit
            "claims": [441, 120, 103, 326],
            "delay": [17.9, 12.6, 21.8, 18.6],
        }
    )


def bubble(**kw: object):
    args = {"title": "NPS vs on-time", "type": "scatter", "x": "on_time", "y": "nps", **kw}
    return build_chart(lanes(), COLS, ChartIntent(**args))


def layers(chart) -> dict[str, dict]:
    return {layer["name"]: layer for layer in chart.spec["layer"]}


def test_bubbles_carry_size_colour_and_labels() -> None:
    chart = bubble(size="claims", color="delay", label="lane")
    by = layers(chart)
    enc = by["points"]["encoding"]
    assert enc["size"]["field"] == "size" and enc["size"]["title"] == "claims"
    assert enc["color"]["type"] == "quantitative" and enc["color"]["title"] == "delay"
    assert {d["label"] for d in chart.spec["data"]["values"]} == set(LANES)
    assert by["labels"]["mark"]["type"] == "text"
    tooltip_fields = {t["field"] for t in enc["tooltip"]}
    assert {"label", "x", "y", "size", "series"} <= tooltip_fields


def test_trend_line_is_least_squares_fit() -> None:
    chart = bubble()
    trend = layers(chart)["trend"]
    (a, b) = trend["data"]["values"]
    assert (a["x"], a["y"]) == (60.0, 0.0) and (b["x"], b["y"]) == (90.0, 30.0)
    assert "r = 1.00" in chart.summary and "slope 1.00" in chart.summary
    assert 1.0 in chart.values


def test_summary_names_largest_bubble() -> None:
    chart = bubble(size="claims", label="lane")
    assert "Largest claims: AEU (441)" in chart.summary


def test_labels_are_dropped_when_crowded() -> None:
    n = LABEL_MAX_POINTS + 1
    table = parquet(
        {
            "name": [f"p{i}" for i in range(n)],
            "a": [float(i) for i in range(n)],
            "b": [float(i % 7) for i in range(n)],
        }
    )
    cols = [
        {"name": "name", "type": "VARCHAR"},
        {"name": "a", "type": "DOUBLE"},
        {"name": "b", "type": "DOUBLE"},
    ]
    chart = build_chart(
        table, cols, ChartIntent(title="many", type="scatter", x="a", y="b", label="name")
    )
    assert "labels" not in layers(chart)
    assert "tooltip" in chart.summary


def test_categorical_colour_keeps_the_three_series_cap() -> None:
    chart = bubble(color="lane")  # 4 lanes: more than a scatter can colour distinctly
    assert "color" not in layers(chart)["points"]["encoding"]
    assert "too many values to colour by" in chart.summary


@pytest.mark.parametrize(
    ("kw", "fragment"),
    [
        ({"size": "lane"}, "size column 'lane' is text"),
        ({"type": "bar", "x": "lane", "y": "nps", "size": "claims"}, "only for scatter"),
        ({"type": "bar", "x": "lane", "y": "nps", "label": "lane"}, "only for scatter"),
    ],
)
def test_invalid_bubble_options(kw: dict, fragment: str) -> None:
    with pytest.raises(ChartError) as exc:
        bubble(**kw)
    assert fragment in exc.value.user_message


def test_bubble_spec_is_safe() -> None:
    text = json.dumps(bubble(size="claims", color="delay", label="lane").spec)
    assert "#" not in text and "expr" not in text and "http" not in text
