import { describe, expect, it } from "vitest";

import {
  bucketTick,
  categoryBars,
  costByModel,
  costPoints,
  donut,
  numberFormat,
  outcomeBars,
  rankedBars,
  timeSeries,
} from "./admin-charts";
import { fileSize, money, pct, ratePct, seconds } from "./admin-format";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = Record<string, any>;
const light = (c: { option: (dark: boolean) => unknown }) => c.option(false) as Json;

describe("admin charts (ECharts)", () => {
  it("formats numbers the console uses", () => {
    expect(numberFormat("$,.2f")(1234.5)).toBe("$1,234.50");
    expect(numberFormat(",d")(12345.4)).toBe("12,345");
    expect(numberFormat(".1f")(2.345)).toBe("2.3");
    expect(numberFormat(".1%")(0.256)).toBe("25.6%");
  });

  it("labels UTC buckets the same in every timezone", () => {
    const ms = Date.parse("2026-11-13T14:00:00Z");
    expect(bucketTick(ms, true)).toBe("14:00");
    expect(bucketTick(ms, false)).toBe("13 Nov");
  });

  it("a single-series line has no legend; ticks sit on whole buckets", () => {
    const o = light(timeSeries([{ x: "2026-11-13", y: 3 }, { x: "2026-11-14", y: 5 }], "answers"));
    expect(o.series).toHaveLength(1);
    expect(o.series[0].type).toBe("line");
    expect(o.legend.show).toBe(false);
    expect(o.useUTC).toBe(true);
    expect(o.xAxis.interval).toBe(86_400_000);
    expect(o.series[0].data[0]).toEqual([Date.parse("2026-11-13T00:00:00Z"), 3]);
    const hourly = light(timeSeries([{ x: "2026-11-13T01:00:00Z", y: 1 }], "answers", { hourly: true }));
    expect(hourly.xAxis.interval).toBe(3 * 3_600_000);
  });

  it("series keep their colour by the fixed order, not by which ones have data", () => {
    const order = ["Planning", "Search", "Answer"];
    const one = light(timeSeries([{ x: "2026-11-13", y: 1, series: "Answer" }], "s", { seriesOrder: order }));
    const all = light(
      timeSeries(order.map((s) => ({ x: "2026-11-13", y: 1, series: s })), "s", { seriesOrder: order }),
    );
    expect(one.series[0].color).toBe(all.series[2].color);
    expect(all.legend.show).not.toBe(false);
  });

  it("pins the x-axis to the period when a domain is given", () => {
    const o = light(timeSeries([{ x: "2026-11-13", y: 1 }], "s", { domain: ["2026-11-01", "2026-11-14"] }));
    expect(o.xAxis.min).toBe(Date.parse("2026-11-01T00:00:00Z"));
  });

  it("fills missing days per model so lines don't skip", () => {
    const points = costPoints([
      { day: "2026-11-12", model_id: "a", cost_usd: 1 },
      { day: "2026-11-13", model_id: "b", cost_usd: 2 },
    ]);
    expect(points).toHaveLength(4);
    expect(points.find((p) => p.x === "2026-11-12" && p.series === "b")?.y).toBe(0);
    expect(light(costByModel([{ day: "2026-11-12", model_id: "a", cost_usd: 1 }])).yAxis.axisLabel.formatter(2)).toBe("$2.00");
  });

  it("category bars: largest first, whole-number ticks", () => {
    const o = light(categoryBars([{ label: "small", value: 1 }, { label: "big", value: 9 }], "events"));
    expect(o.yAxis.data).toEqual(["big", "small"]);
    expect(o.series[0].data).toEqual([9, 1]);
    expect(o.xAxis.minInterval).toBe(1);
  });

  it("donut colours follow the model, not its rank, with Other last", () => {
    const rows = [{ label: "zeta", value: 9 }, { label: "alpha", value: 1 }, { label: "Other", value: 2 }];
    const o = light(donut(rows, { value: "$12", caption: "total" }));
    expect(o.legend.data).toEqual(["alpha", "zeta", "Other"]);
    const colour = (name: string) => o.series[0].data.find((d: Json) => d.name === name).itemStyle.color;
    const swapped = light(donut([{ label: "zeta", value: 1 }, { label: "alpha", value: 9 }], { value: "", caption: "" }));
    const colour2 = (name: string) => swapped.series[0].data.find((d: Json) => d.name === name).itemStyle.color;
    expect(colour("alpha")).toBe(colour2("alpha"));
    expect(o.title.text).toBe("$12");
  });

  it("outcome bars stack three outcomes in the fixed status colours", () => {
    const o = light(outcomeBars([{ bucket: "2026-11-13", succeeded: 5, failed: 1, other: 0 }], false));
    expect(o.series.map((s: Json) => s.color)).toEqual(["#0ca30c", "#d03b3b", "#898781"]);
    expect(o.series.every((s: Json) => s.stack === "outcomes")).toBe(true);
    expect(o.xAxis.data).toEqual(["13 Nov"]);
  });

  it("ranked bars sort high to low and print their values", () => {
    const o = light(rankedBars([{ label: "fast", value: 0.1 }, { label: "slow", value: 9.9 }], { title: "avg s", format: ".1f" }));
    expect(o.yAxis.data).toEqual(["slow", "fast"]);
    expect(o.series[0].label.show).toBe(true);
    expect(o.series[0].label.formatter({ value: 9.9 })).toBe("9.9");
  });

  it("dark mode builds its own colours; the key changes only with the data", () => {
    const chart = categoryBars([{ label: "a", value: 2 }], "events");
    expect((chart.option(true) as Json).series[0].color).not.toBe(light(chart).series[0].color);
    expect(categoryBars([{ label: "a", value: 2 }], "events").key).toBe(chart.key);
    expect(categoryBars([{ label: "a", value: 3 }], "events").key).not.toBe(chart.key);
  });
});

describe("admin format", () => {
  it("formats money, percentages and durations", () => {
    expect(money(1234.5)).toBe("$1,234.50");
    expect(money(0.0042)).toBe("$0.0042");
    expect(money(null)).toBe("—");
    expect(pct(1, 3)).toBe("33%");
    expect(pct(1, 40)).toBe("2.5%");
    expect(pct(1, 0)).toBe("—");
    expect(seconds(null)).toBe("n/a");
    expect(seconds(2.345)).toBe("2.3 s");
    expect(ratePct(0.9512)).toBe("95%");
    expect(ratePct(0.025)).toBe("2.5%");
    expect(ratePct(null)).toBe("—");
    expect(fileSize(512)).toBe("512 B");
    expect(fileSize(2048)).toBe("2 KB");
    expect(fileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
