import { describe, expect, it } from "vitest";

import { categoryBars, costByModel, timeSeries } from "./admin-charts";
import { fileSize, money, pct, seconds } from "./admin-format";

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
    expect(fileSize(512)).toBe("512 B");
    expect(fileSize(2048)).toBe("2 KB");
    expect(fileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
