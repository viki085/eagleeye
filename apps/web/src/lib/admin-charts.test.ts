import { describe, expect, it } from "vitest";

import { categoryBars, costByModel, donut, outcomeBars, rankedBars, timeSeries } from "./admin-charts";
import { fileSize, money, pct, ratePct, seconds } from "./admin-format";

describe("admin charts", () => {
  it("builds a single-series line without a colour encoding", () => {
    const spec = timeSeries([{ x: "2026-11-13", y: 3 }], "answers") as {
      encoding: Record<string, unknown>;
      mark: { type: string };
    };
    expect(spec.mark.type).toBe("line");
    expect(spec.encoding.color).toBeUndefined();
  });

  it("puts daily ticks on day boundaries, hourly every 3 hours", () => {
    type S = { encoding: { x: { axis: { tickCount: unknown } } } };
    const daily = timeSeries([{ x: "2026-11-13", y: 1 }], "answers") as S;
    const hourly = timeSeries([{ x: "2026-11-13T01:00Z", y: 1 }], "answers", { hourly: true }) as S;
    expect(daily.encoding.x.axis.tickCount).toEqual({ interval: "day", step: 1 });
    expect(hourly.encoding.x.axis.tickCount).toEqual({ interval: "hours", step: 3 });
  });

  it("only uses interval names Vega knows (an unknown one crashes the chart)", async () => {
    // @ts-expect-error vega-time (a vega dependency) ships no type declarations
    const { utcInterval } = (await import("vega-time")) as { utcInterval: (n: string) => unknown };
    for (const opts of [{}, { hourly: true }]) {
      const spec = timeSeries([{ x: "2026-11-13", y: 1 }], "answers", opts) as {
        encoding: { x: { axis: { tickCount: { interval: string } } } };
      };
      expect(utcInterval(spec.encoding.x.axis.tickCount.interval)).toBeDefined();
    }
  });

  it("fills missing days per model so lines don't skip", () => {
    const spec = costByModel([
      { day: "2026-11-12", model_id: "a", cost_usd: 1 },
      { day: "2026-11-13", model_id: "b", cost_usd: 2 },
    ]) as { data: { values: { x: string; y: number; series: string }[] } };
    expect(spec.data.values).toHaveLength(4);
    expect(spec.data.values.find((p) => p.x === "2026-11-12" && p.series === "b")?.y).toBe(0);
  });

  it("sorts category bars largest first and carries no colours", () => {
    const spec = categoryBars(
      [
        { label: "small", value: 1 },
        { label: "big", value: 9 },
      ],
      "events",
    );
    const enc = (spec as { encoding: { y: { sort: string[] } } }).encoding;
    expect(enc.y.sort).toEqual(["big", "small"]);
    expect(JSON.stringify(spec)).not.toContain("#");
  });

  it("uses whole-number ticks on count bars", () => {
    const spec = categoryBars([{ label: "a", value: 2 }], "events") as {
      encoding: { x: { axis: { tickMinStep: number; format: string; tickCount: number } } };
    };
    expect(spec.encoding.x.axis).toEqual({ tickMinStep: 1, format: "d", tickCount: 6 });
  });
});

describe("overview charts", () => {
  it("donut colours follow the model, not its rank, with Other last", () => {
    const a = donut([{ label: "zeta", value: 9 }, { label: "alpha", value: 1 }, { label: "Other", value: 2 }], { value: "$12", caption: "total" }) as {
      layer: { encoding?: { color?: { scale: { domain: string[] } } } }[];
    };
    expect(a.layer[0].encoding?.color?.scale.domain).toEqual(["alpha", "zeta", "Other"]);
  });

  it("outcome bars stack three outcomes in the fixed status colours", () => {
    const spec = outcomeBars([{ bucket: "2026-11-13", succeeded: 5, failed: 1, other: 0 }], false) as {
      data: { values: unknown[] };
      encoding: { color: { scale: { range: string[] } } };
    };
    expect(spec.data.values).toHaveLength(3);
    expect(spec.encoding.color.scale.range).toEqual(["#0ca30c", "#d03b3b", "#898781"]);
  });

  it("ranked bars sort high to low and print values", () => {
    const spec = rankedBars([{ label: "fast", value: 0.1 }, { label: "slow", value: 9.9 }], { title: "avg s", format: ".1f" }) as {
      encoding: { y: { sort: string[] } };
      layer: { mark: { type: string } }[];
    };
    expect(spec.encoding.y.sort).toEqual(["slow", "fast"]);
    expect(spec.layer.map((l) => l.mark.type)).toEqual(["bar", "text"]);
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
