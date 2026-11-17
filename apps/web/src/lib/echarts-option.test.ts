import { describe, expect, it } from "vitest";

import { toEChartsOption } from "./echarts-option";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = Record<string, any>;
const opt = (spec: Json, dark = false) => toEChartsOption(spec, dark) as Json;
// a bar's value (rounded bars carry their own style: {value, itemStyle})
const values = (data: unknown[]) => data.map((d) => (d !== null && typeof d === "object" ? (d as Json).value : d));

const bar = {
  mark: { type: "bar", cornerRadiusEnd: 3 },
  encoding: {
    x: { field: "x", type: "nominal", sort: ["EMEA", "APAC"], title: "region" },
    y: { field: "y", type: "quantitative", title: "sum of revenue" },
  },
  data: { values: [{ x: "APAC", series: null, y: 185.5 }, { x: "EMEA", series: null, y: 310 }] },
  height: 280,
};

const monthly = [
  { x: "Jan", series: "EMEA", y: 1 },
  { x: "Jan", series: "APAC", y: 2 },
  { x: "Feb", series: "EMEA", y: 3 },
  { x: "Feb", series: "APAC", y: 4 },
];
const byMonth = { ...bar.encoding.x, sort: ["Jan", "Feb"] };

describe("toEChartsOption", () => {
  it("bars keep the server's order and values", () => {
    const o = opt(bar);
    expect(o.xAxis.data).toEqual(["EMEA", "APAC"]);
    expect(o.series).toHaveLength(1);
    expect(values(o.series[0].data)).toEqual([310, 185.5]);
    expect(o.yAxis.name).toBe("sum of revenue");
  });

  it("a colour column stacks; several measures sit side by side", () => {
    const color = { field: "series" };
    const stacked = opt({ ...bar, encoding: { ...bar.encoding, x: byMonth, color }, data: { values: monthly } });
    expect(stacked.series.map((s: Json) => s.stack)).toEqual(["total", "total"]);
    expect(values(stacked.series[1].data)).toEqual([2, 4]);
    const grouped = opt({
      ...bar,
      encoding: { ...bar.encoding, x: byMonth, color, xOffset: color },
      data: { values: monthly },
    });
    expect(grouped.series.every((s: Json) => s.stack === undefined)).toBe(true);
  });

  it("horizontal bars put the categories on y", () => {
    const o = opt({ ...bar, encoding: { y: bar.encoding.x, x: bar.encoding.y } });
    expect(o.yAxis.type).toBe("category");
    expect(o.yAxis.data).toEqual(["EMEA", "APAC"]);
  });

  it("time lines become one series per colour; years get whole ticks", () => {
    const line = {
      mark: { type: "line" },
      encoding: {
        x: { field: "x", type: "temporal", title: "month" },
        y: { field: "y", type: "quantitative", title: "revenue" },
        color: { field: "series" },
      },
      data: { values: [{ x: "2026-01-01", series: "A", y: 1 }, { x: "2026-02-01", series: "B", y: 2 }] },
    };
    const o = opt(line);
    expect(o.xAxis.type).toBe("time");
    expect(o.series.map((s: Json) => s.name)).toEqual(["A", "B"]);
    const years = opt({
      mark: { type: "line" },
      encoding: {
        x: { field: "x", type: "quantitative", title: "year", axis: { format: "d", tickMinStep: 1 } },
        y: { field: "y", type: "quantitative", title: "count" },
      },
      data: { values: [{ x: 2023, series: null, y: 5 }, { x: 2024, series: null, y: 6 }] },
    });
    expect(years.xAxis.minInterval).toBe(1);
    expect(years.xAxis.axisLabel.formatter(2023)).toBe("2023");
  });

  it("areas get a fill", () => {
    const o = opt({
      mark: { type: "area" },
      encoding: { x: { field: "x", type: "temporal" }, y: { field: "y", type: "quantitative" } },
      data: { values: [{ x: "2026-01-01", y: 1 }, { x: "2026-02-01", y: 2 }] },
    });
    expect(o.series[0].areaStyle).toBeDefined();
  });

  it("histograms show bin ranges", () => {
    const o = opt({
      mark: { type: "bar" },
      encoding: {
        x: { field: "x", type: "quantitative", bin: { binned: true }, title: "revenue" },
        x2: { field: "x2" },
        y: { field: "y", type: "quantitative", title: "count" },
      },
      data: { values: [{ x: 50, x2: 53.5, y: 1 }] },
    });
    expect(o.xAxis.data).toEqual(["50–53.5"]);
  });

  it("scatter: bubbles, numeric colour scale, trend line, labelled text-only tooltips", () => {
    const spec = {
      layer: [
        { name: "trend", data: { values: [{ x: 10, y: 5 }, { x: 15, y: 10 }] }, mark: { type: "line" } },
        {
          name: "points",
          mark: { type: "circle" },
          encoding: {
            x: { field: "x", type: "quantitative", title: "speed" },
            y: { field: "y", type: "quantitative", title: "co2" },
            size: { field: "size", type: "quantitative", title: "units" },
            color: { field: "series", type: "quantitative", title: "revenue" },
            tooltip: [{ field: "label", title: "vessel" }],
          },
        },
      ],
      data: {
        values: [
          { x: 14, y: 9, size: 7, series: 70, label: "<b>e</b>" },
          { x: 10, y: 5, size: 3, series: 10, label: "a" },
        ],
      },
    };
    const o = opt(spec);
    expect(o.series[0].type).toBe("scatter");
    expect(o.series.at(-1).name).toBe("trend");
    expect(o.visualMap.dimension).toBe(3);
    expect(o.tooltip.renderMode).toBe("richText"); // drawn as text, never parsed as HTML
    expect(o.tooltip.formatter({ data: [14, 9, 7, 70, "<b>e</b>"] })).toContain("vessel: <b>e</b>");
    expect(o.series[0].label).toBeUndefined(); // no labels layer: names stay in the tooltip
  });

  it("scatter: points are named on the chart when the server sends a labels layer", () => {
    const spec = {
      layer: [
        {
          name: "points",
          mark: { type: "circle" },
          encoding: {
            x: { field: "x", type: "quantitative", title: "on-time %" },
            y: { field: "y", type: "quantitative", title: "NPS" },
            tooltip: [{ field: "label", title: "lane" }],
          },
        },
        { name: "labels", mark: { type: "text" }, encoding: { text: { field: "label", type: "nominal" } } },
      ],
      data: { values: [{ x: 80, y: 12, label: "TAT" }, { x: 73, y: 9.6, label: "IAS" }] },
    };
    const s = opt(spec).series[0];
    expect(s.label.show).toBe(true);
    expect(s.label.formatter({ data: [80, 12, null, null, "TAT"] })).toBe("TAT");
    expect(s.labelLayout.hideOverlap).toBe(true);
  });

  it("bars are rounded at their outer end, also when negative", () => {
    const spec = { ...bar, data: { values: [{ x: "EMEA", series: null, y: 310 }, { x: "APAC", series: null, y: -40 }] } };
    const [up, down] = opt(spec).series[0].data;
    expect(up.itemStyle.borderRadius).toEqual([5, 5, 0, 0]);
    expect(down.itemStyle.borderRadius).toEqual([0, 0, 5, 5]);
    const flat = { ...spec, encoding: { x: { field: "y", type: "quantitative" }, y: { field: "x", type: "nominal", sort: ["EMEA", "APAC"] } } };
    const [right, left] = opt(flat).series[0].data;
    expect(right.itemStyle.borderRadius).toEqual([0, 5, 5, 0]);
    expect(left.itemStyle.borderRadius).toEqual([5, 0, 0, 5]);
  });

  it("heatmap: cells on two category axes, one sequential hue, values while few", () => {
    const spec = {
      mark: { type: "rect", tooltip: true },
      encoding: {
        x: { field: "x", type: "nominal", sort: ["2026-01", "2026-02"], title: "month" },
        y: { field: "series", type: "nominal", sort: ["TAT", "AEU"], title: "lane" },
        color: { field: "y", type: "quantitative", title: "mean of delay" },
      },
      data: { values: [{ x: "2026-02", series: "AEU", y: 3 }, { x: "2026-01", series: "TAT", y: 4 }] },
    };
    const o = opt(spec);
    expect(o.series[0].type).toBe("heatmap");
    expect(o.xAxis.data).toEqual(["2026-01", "2026-02"]);
    expect(o.yAxis.data).toEqual(["TAT", "AEU"]);
    expect(o.series[0].data).toEqual([[1, 1, 3], [0, 0, 4]]);
    expect(o.visualMap.inRange.color.length).toBeGreaterThan(1);
    expect(o.series[0].label.show).toBe(true);
    expect(o.tooltip.formatter({ data: [1, 1, 3] })).toBe("lane: AEU\nmonth: 2026-02\nmean of delay: 3");
  });

  it("unknown shapes fall back to Vega (null)", () => {
    expect(toEChartsOption({ mark: { type: "arc" }, encoding: {}, data: { values: [{ x: 1 }] } }, false)).toBeNull();
    expect(toEChartsOption({ mark: "bar", data: { values: [] } }, false)).toBeNull();
  });

  it("dark mode uses the dark palette", () => {
    expect(opt(bar, true).color[0]).not.toBe(opt(bar, false).color[0]);
  });
});
