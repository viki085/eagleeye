import io
import json
from datetime import date, timedelta

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from eagleeye_charts.build import OTHER, assert_safe, build_chart
from eagleeye_charts.downsample import lttb
from eagleeye_charts.intent import MAX_POINTS, MAX_SERIES, ChartError, ChartIntent

COLUMNS = [
    {"name": "region", "type": "VARCHAR"},
    {"name": "month", "type": "DATE"},
    {"name": "revenue", "type": "DOUBLE"},
    {"name": "units", "type": "BIGINT"},
]


def parquet(table: dict) -> bytes:
    buf = io.BytesIO()
    pq.write_table(pa.table(table), buf)
    return buf.getvalue()


def sales() -> bytes:
    months = [date(2026, m, 1) for m in (1, 2, 3)]
    return parquet(
        {
            "region": ["EMEA"] * 3 + ["APAC"] * 3,
            "month": months * 2,
            "revenue": [100.0, 120.0, 90.0, 50.0, 70.0, 65.5],
            "units": [10, 12, 9, 5, 7, 6],
        }
    )


def intent(**kw: object) -> ChartIntent:
    return ChartIntent(**{"title": "Test chart", **kw})


def test_bar_aggregates_in_code_and_sorts_by_value() -> None:
    chart = build_chart(sales(), COLUMNS, intent(type="bar", x="region", y="revenue"))
    data = chart.spec["data"]["values"]
    assert {d["x"]: d["y"] for d in data} == {"EMEA": 310.0, "APAC": 185.5}
    assert chart.spec["encoding"]["x"]["sort"] == ["EMEA", "APAC"]
    assert "Highest: EMEA (310)" in chart.summary and "Total: 495.50" in chart.summary
    assert 310.0 in chart.values and 495.5 in chart.values


def test_bar_counts_rows_when_y_is_omitted() -> None:
    chart = build_chart(sales(), COLUMNS, intent(type="bar", x="region"))
    assert {d["y"] for d in chart.spec["data"]["values"]} == {3.0}
    assert chart.spec["encoding"]["y"]["title"] == "count"


def test_bar_top_n_folds_the_rest_into_other() -> None:
    table = parquet({"k": [f"c{i:02d}" for i in range(30)], "v": [float(i) for i in range(30)]})
    cols = [{"name": "k", "type": "VARCHAR"}, {"name": "v", "type": "DOUBLE"}]
    chart = build_chart(table, cols, intent(type="bar", x="k", y="v", top_n=5))
    labels = chart.spec["encoding"]["x"]["sort"]  # 6 short labels → vertical bars
    assert labels == ["c29", "c28", "c27", "c26", "c25", OTHER]
    other = next(d for d in chart.spec["data"]["values"] if d["x"] == OTHER)
    assert other["y"] == sum(range(25)) and "combined into 'Other'" in chart.summary
    mean = build_chart(table, cols, intent(type="bar", x="k", y="v", top_n=5, aggregate="mean"))
    assert OTHER not in mean.spec["encoding"]["x"]["sort"] and "top 5 of 30" in mean.summary
    many = build_chart(table, cols, intent(type="bar", x="k", y="v", top_n=12))
    assert many.spec["encoding"]["y"]["type"] == "nominal"  # ≥ 9 bars → horizontal


def test_line_is_temporal_ordered_and_has_series() -> None:
    chart = build_chart(
        sales(), COLUMNS, intent(type="line", x="month", y="revenue", color="region")
    )
    enc = chart.spec["encoding"]
    assert enc["x"]["type"] == "temporal" and enc["color"]["field"] == "series"
    emea = [d for d in chart.spec["data"]["values"] if d["series"] == "EMEA"]
    assert [d["x"] for d in emea] == ["2026-01-01", "2026-02-01", "2026-03-01"]
    assert "from 2026-01-01 to 2026-03-01, 2 series" in chart.summary


def test_long_line_is_downsampled_keeping_extremes() -> None:
    n = 10_000
    days = [date(2000, 1, 1) + timedelta(days=i) for i in range(n)]
    values = [float(i % 100) for i in range(n)]
    values[5000] = 9999.0
    table = parquet({"d": days, "v": values})
    cols = [{"name": "d", "type": "DATE"}, {"name": "v", "type": "DOUBLE"}]
    chart = build_chart(table, cols, intent(type="area", x="d", y="v"))
    data = chart.spec["data"]["values"]
    assert len(data) <= MAX_POINTS and max(d["y"] for d in data) == 9999.0
    assert chart.spec["mark"]["type"] == "area" and "downsampled" in chart.summary


def test_series_beyond_the_cap_fold_into_other() -> None:
    table = parquet(
        {
            "x": [1, 2] * 12,
            "s": [f"s{i:02d}" for i in range(12) for _ in range(2)],
            "v": [float(i + 1) for i in range(12) for _ in range(2)],
        }
    )
    cols = [
        {"name": "x", "type": "BIGINT"},
        {"name": "s", "type": "VARCHAR"},
        {"name": "v", "type": "DOUBLE"},
    ]
    chart = build_chart(table, cols, intent(type="line", x="x", y="v", color="s"))
    series = {d["series"] for d in chart.spec["data"]["values"]}
    assert len(series) == MAX_SERIES and OTHER in series


def test_scatter_reports_correlation_and_samples() -> None:
    n = 5000
    table = parquet({"a": [float(i) for i in range(n)], "b": [float(i * 2) for i in range(n)]})
    cols = [{"name": "a", "type": "DOUBLE"}, {"name": "b", "type": "DOUBLE"}]
    chart = build_chart(table, cols, intent(type="scatter", x="a", y="b"))
    assert len(chart.spec["data"]["values"]) == MAX_POINTS
    assert "r = 1.00" in chart.summary and "sample of 2,000 of 5,000" in chart.summary


def test_histogram_bins_cover_every_value() -> None:
    chart = build_chart(sales(), COLUMNS, intent(type="histogram", x="revenue"))
    data = chart.spec["data"]["values"]
    assert sum(d["y"] for d in data) == 6 and data[0]["x"] == 50.0 and data[-1]["x2"] == 120.0
    assert chart.spec["encoding"]["x"]["bin"] == {"binned": True}


@pytest.mark.parametrize(
    ("kw", "fragment"),
    [
        ({"type": "bar", "x": "nope", "y": "revenue"}, "Unknown column 'nope'"),
        ({"type": "bar", "x": "region", "y": "month"}, "not numeric"),
        ({"type": "line", "x": "region", "y": "revenue"}, "Use a bar chart"),
        ({"type": "scatter", "x": "revenue"}, "both x and y"),
        ({"type": "histogram", "x": "region"}, "numeric x"),
        ({"type": "bar", "x": "region", "aggregate": "mean"}, "needs a y column"),
    ],
)
def test_invalid_intents_explain_themselves(kw: dict, fragment: str) -> None:
    with pytest.raises(ChartError) as exc:
        build_chart(sales(), COLUMNS, intent(**kw))
    assert fragment in exc.value.user_message


@pytest.mark.parametrize("kind", ["bar", "line", "area", "scatter", "histogram"])
def test_specs_carry_no_colours_expressions_or_urls(kind: str) -> None:
    x = {"bar": "region", "line": "month", "area": "month"}.get(kind, "revenue")
    y = None if kind == "histogram" else "units"
    chart = build_chart(sales(), COLUMNS, intent(type=kind, x=x, y=y))
    text = json.dumps(chart.spec)
    assert "#" not in text and "expr" not in text and "http" not in text
    assert chart.spec["description"].startswith("Test chart.")


def test_assert_safe_rejects_executable_keys() -> None:
    with pytest.raises(ChartError):
        assert_safe({"mark": "bar", "encoding": {"x": {"transform": [{"calculate": "1"}]}}})


def _plan() -> bytes:
    return parquet(
        {
            "month": [date(2026, m, 1) for m in (1, 2, 3)],
            "revenue": [2_100_000.0, 1_900_000.0, 2_200_000.0],
            "target": [2_000_000.0, 2_100_000.0, 2_100_000.0],
            "status": ["matched"] * 3,
        }
    )


PLAN_COLUMNS = [
    {"name": "month", "type": "DATE"},
    {"name": "revenue", "type": "DOUBLE"},
    {"name": "target", "type": "DOUBLE"},
    {"name": "status", "type": "VARCHAR"},
]


def test_several_measures_are_grouped_bars_with_month_labels() -> None:
    chart = build_chart(
        _plan(), PLAN_COLUMNS, intent(type="bar", x="month", y=["revenue", "target"])
    )
    enc = chart.spec["encoding"]
    assert enc["x"]["sort"] == ["2026-01", "2026-02", "2026-03"]  # vertical, month labels
    assert enc["xOffset"] == {"field": "series"} and enc["color"]["title"] == "measure"
    feb = {d["series"]: d["y"] for d in chart.spec["data"]["values"] if d["x"] == "2026-02"}
    assert feb == {"revenue": 1_900_000.0, "target": 2_100_000.0}
    assert "revenue: highest 2026-03 (2,200,000), lowest 2026-02 (1,900,000)" in chart.summary
    assert "target: highest 2026-02 (2,100,000)" in chart.summary


def test_several_measures_as_lines_and_unstacked_areas() -> None:
    line = build_chart(
        _plan(), PLAN_COLUMNS, intent(type="line", x="month", y=["revenue", "target"])
    )
    assert {d["series"] for d in line.spec["data"]["values"]} == {"revenue", "target"}
    area = build_chart(
        _plan(), PLAN_COLUMNS, intent(type="area", x="month", y=["revenue", "target"])
    )
    assert area.spec["encoding"]["y"]["stack"] is None


def test_text_months_are_treated_as_time() -> None:
    table = parquet(
        {
            "month": ["2026-03", "2026-01", "2026-02"],
            "gap": [5.0, -10.0, 20.0],
            "target": [1.0, 2.0, 3.0],
        }
    )
    cols = [
        {"name": "month", "type": "VARCHAR"},
        {"name": "gap", "type": "DOUBLE"},
        {"name": "target", "type": "DOUBLE"},
    ]
    bar = build_chart(table, cols, intent(type="bar", x="month", y="gap"))
    assert bar.spec["encoding"]["x"]["sort"] == ["2026-01", "2026-02", "2026-03"]  # by month
    line = build_chart(table, cols, intent(type="line", x="month", y=["gap", "target"]))
    assert line.spec["encoding"]["x"]["type"] == "temporal"


def test_numeric_text_columns_are_plotted_as_numbers() -> None:
    table = parquet({"month": ["2026-01", "2026-02"], "target": ["2100000", "2150000"]})
    cols = [{"name": "month", "type": "VARCHAR"}, {"name": "target", "type": "VARCHAR"}]
    chart = build_chart(table, cols, intent(type="bar", x="month", y="target"))
    assert [d["y"] for d in chart.spec["data"]["values"]] == [2_100_000.0, 2_150_000.0]


def test_measure_present_only_in_second_series_still_counts_as_a_group() -> None:
    table = parquet(
        {
            "month": [date(2026, 1, 1), date(2026, 2, 1)],
            "revenue": [10.0, None],
            "target": [9.0, 12.0],
        }
    )
    cols = [
        {"name": "month", "type": "DATE"},
        {"name": "revenue", "type": "DOUBLE"},
        {"name": "target", "type": "DOUBLE"},
    ]
    chart = build_chart(table, cols, intent(type="bar", x="month", y=["revenue", "target"]))
    assert chart.spec["encoding"]["x"]["sort"] == ["2026-01", "2026-02"]
    assert "2 groups" in chart.summary


def test_single_valued_color_column_is_dropped() -> None:
    chart = build_chart(
        _plan(), PLAN_COLUMNS, intent(type="bar", x="month", y="revenue", color="status")
    )
    assert "color" not in chart.spec["encoding"]


@pytest.mark.parametrize(
    ("kw", "fragment"),
    [
        ({"y": ["revenue", "target"], "color": "status"}, "not both"),
        ({"y": ["revenue", "status"]}, "not numeric"),
        ({"y": ["revenue", "target", "revenue", "target", "x"]}, "At most 4"),
    ],
)
def test_measure_errors(kw: dict, fragment: str) -> None:
    with pytest.raises(ChartError) as exc:
        build_chart(_plan(), PLAN_COLUMNS, intent(type="bar", x="month", **kw))
    assert fragment in exc.value.user_message


def test_lttb_keeps_endpoints_and_size() -> None:
    points = [(float(i), float(i % 10)) for i in range(1000)]
    keep = lttb(points, 100)
    assert len(keep) == 100 and keep[0] == 0 and keep[-1] == 999
    assert lttb(points[:5], 100) == [0, 1, 2, 3, 4]
