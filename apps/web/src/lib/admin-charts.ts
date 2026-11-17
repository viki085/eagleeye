/**
 * ECharts options for the admin console, built from API data with the same theme as the answer
 * charts (lib/echarts-option.ts: the validated palette, light and dark). Lines for time series,
 * horizontal bars for categories; one axis per chart (never dual-axis). Outcome bars use the
 * reserved status colours, always with a legend.
 */

import { STATUS } from "./chart-theme";
import { axisStyle, base, type EChartsOption, theme, type Theme } from "./echarts-option";

/** One admin chart: `option` is built for light or dark; `key` changes only with the data. */
export interface AdminChart {
  key: string;
  height: number;
  option: (dark: boolean) => EChartsOption;
}

type Json = Record<string, unknown>;

interface Point {
  x: string;
  y: number;
  series?: string;
}

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const POINT_MARKS_MAX = 40;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** d3-style number formats used by the console: "$,.2f", ",d", ".1f", ".1%". */
export function numberFormat(spec: string): (v: number) => string {
  const m = /^(\$)?(,)?(?:\.(\d+))?([dfs%])?$/.exec(spec) ?? [];
  const [, dollar, group, digits, type] = m;
  return (v: number) => {
    if (!Number.isFinite(v)) return "—";
    const percent = type === "%";
    const value = percent ? v * 100 : v;
    const decimals = type === "d" ? 0 : digits !== undefined ? Number(digits) : 2;
    const text = (type === "d" ? Math.round(value) : value).toLocaleString("en-US", {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
      useGrouping: Boolean(group),
    });
    return `${dollar ? "$" : ""}${text}${percent ? "%" : ""}`;
  };
}

/** A UTC bucket as the console shows it: "14:00" (hourly) or "13 Nov" (daily). */
export function bucketTick(ms: number, hourly: boolean): string {
  const d = new Date(ms);
  if (hourly) return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
}

const toMs = (x: string): number => Date.parse(x.length === 10 ? `${x}T00:00:00Z` : x);
const keyOf = (...parts: unknown[]): string => JSON.stringify(parts);

function tooltip(t: Theme, trigger: "axis" | "item", extra: Json = {}): Json {
  return { ...(base(t, false, trigger).tooltip as Json), ...extra };
}

export function timeSeries(
  points: Point[],
  yTitle: string,
  opts: {
    money?: boolean;
    hourly?: boolean;
    seriesOrder?: readonly string[];
    format?: string;
    domain?: [string, string]; // pin the x-axis to the whole period, even where data is sparse
  } = {},
): AdminChart {
  const multi = points.some((p) => p.series !== undefined);
  const present = [...new Set(points.map((p) => p.series ?? ""))];
  // a fixed order keeps each entity's colour stable across periods
  const order = opts.seriesOrder ? [...opts.seriesOrder] : [...present].sort();
  const names = order.filter((n) => present.includes(n));
  const value = numberFormat(opts.money ? "$,.2f" : opts.format ?? ",.2f");
  const hourly = Boolean(opts.hourly);
  const option = (dark: boolean): EChartsOption => {
    const t = theme(dark);
    const series = (multi ? names : [""]).map((name) => {
      const mine = points.filter((p) => (p.series ?? "") === name).sort((a, b) => toMs(a.x) - toMs(b.x));
      return {
        type: "line",
        name: multi ? name : yTitle,
        data: mine.map((p) => [toMs(p.x), p.y]),
        showSymbol: mine.length <= POINT_MARKS_MAX,
        symbolSize: 6,
        lineStyle: { width: 2 },
        // colour by the entity's place in the fixed order, never by rank
        color: t.palette[Math.max(order.indexOf(name), 0) % t.palette.length],
        emphasis: { focus: "series" },
      };
    });
    return {
      ...base(t, multi, "axis"),
      useUTC: true, // buckets are UTC hours/days
      tooltip: tooltip(t, "axis", {
        valueFormatter: (v: unknown) => value(Number(v)),
        axisPointer: { type: "line", lineStyle: { color: t.axis } },
      }),
      xAxis: axisStyle(t, "", {
        type: "time",
        ...(opts.domain ? { min: toMs(opts.domain[0]), max: toMs(opts.domain[1]) } : {}),
        // ticks on whole buckets: every 3 hours, or one per day
        interval: hourly ? 3 * HOUR_MS : DAY_MS,
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true, formatter: (ms: number) => bucketTick(ms, hourly) },
      }),
      yAxis: axisStyle(t, yTitle, { type: "value", nameGap: 46, axisLabel: { color: t.muted, fontSize: 11, formatter: value } }),
      series,
    };
  };
  return { key: keyOf("ts", points, yTitle, opts), height: 220, option };
}

export function categoryBars(rows: { label: string; value: number }[], xTitle: string): AdminChart {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const count = numberFormat(",d");
  const option = (dark: boolean): EChartsOption => {
    const t = theme(dark);
    return {
      ...base(t, false, "axis"),
      tooltip: tooltip(t, "axis", { valueFormatter: (v: unknown) => count(Number(v)) }),
      yAxis: axisStyle(t, "", {
        type: "category",
        data: sorted.map((r) => r.label),
        inverse: true,
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, width: 180, overflow: "truncate" },
      }),
      // counts: whole-number ticks only
      xAxis: axisStyle(t, xTitle, { type: "value", minInterval: 1, splitNumber: 5, axisLabel: { color: t.muted, fontSize: 11, formatter: count } }),
      series: [
        {
          type: "bar",
          name: xTitle,
          data: sorted.map((r) => r.value),
          color: t.palette[0],
          barMaxWidth: 22,
          itemStyle: { borderRadius: [0, 4, 4, 0] },
        },
      ],
    };
  };
  return { key: keyOf("cat", sorted, xTitle), height: Math.min(360, Math.max(90, 28 * sorted.length + 40)), option };
}

/**
 * Part-to-whole donut (≤ 6 slices; the server folds the rest into "Other"). Colours follow the
 * entity: slots are assigned by label, Other last, so a model keeps its colour across periods.
 */
export function donut(
  rows: { label: string; value: number }[],
  centre: { value: string; caption: string },
  opts: { money?: boolean } = {},
): AdminChart {
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  const domain = [...rows.map((r) => r.label)].sort((a, b) => (a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)));
  const value = numberFormat(opts.money ? "$,.4f" : ",d");
  const share = numberFormat(".1%");
  const option = (dark: boolean): EChartsOption => {
    const t = theme(dark);
    const ordered = [...rows].sort((a, b) => b.value - a.value);
    return {
      ...base(t, false, "item"),
      legend: {
        orient: "vertical", right: 0, top: "middle", icon: "roundRect", itemWidth: 12, itemHeight: 8,
        textStyle: { color: t.muted, fontSize: 11, width: 170, overflow: "truncate" },
        data: domain,
      },
      tooltip: tooltip(t, "item", {
        formatter: (p: Json) => {
          const v = Number(p.value);
          return `${String(p.name)}\n${opts.money ? "Cost" : "Value"}: ${value(v)}\nShare: ${share(total ? v / total : 0)}`;
        },
      }),
      title: {
        text: centre.value, subtext: centre.caption, left: "32%", top: "middle", textAlign: "center", itemGap: 4,
        textStyle: { color: t.text, fontSize: 20, fontWeight: 600 },
        subtextStyle: { color: t.muted, fontSize: 11 },
      },
      series: [
        {
          type: "pie",
          radius: ["58%", "86%"],
          center: ["32%", "50%"],
          padAngle: 1.5,
          avoidLabelOverlap: true,
          label: { show: false },
          itemStyle: { borderRadius: 3, borderColor: t.surface, borderWidth: 2 },
          data: ordered.map((r) => ({
            name: r.label,
            value: r.value,
            itemStyle: { color: t.palette[domain.indexOf(r.label) % t.palette.length] },
          })),
        },
      ],
    };
  };
  return { key: keyOf("donut", rows, centre, opts), height: 220, option };
}

const OUTCOMES = [
  { name: "Succeeded", color: STATUS.good, field: "succeeded" },
  { name: "Failed", color: STATUS.critical, field: "failed" },
  { name: "Cancelled / in progress", color: STATUS.neutral, field: "other" },
] as const;

/** Requests per bucket split by outcome, stacked, in the fixed status colours (with a legend). */
export function outcomeBars(
  points: { bucket: string; succeeded: number; failed: number; other: number }[],
  hourly: boolean,
): AdminChart {
  const sorted = [...points].sort((a, b) => toMs(a.bucket) - toMs(b.bucket));
  const count = numberFormat(",d");
  const option = (dark: boolean): EChartsOption => {
    const t = theme(dark);
    return {
      ...base(t, true, "axis"),
      tooltip: tooltip(t, "axis", { valueFormatter: (v: unknown) => count(Number(v)) }),
      xAxis: axisStyle(t, "", {
        type: "category",
        data: sorted.map((p) => bucketTick(toMs(p.bucket), hourly)),
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true },
      }),
      yAxis: axisStyle(t, "requests", { type: "value", minInterval: 1, nameGap: 40, axisLabel: { color: t.muted, fontSize: 11, formatter: count } }),
      series: OUTCOMES.map((o) => ({
        type: "bar",
        name: o.name,
        stack: "outcomes",
        data: sorted.map((p) => p[o.field]),
        color: o.color,
        barCategoryGap: "30%", // a visible gap between adjacent periods
        emphasis: { focus: "series" },
      })),
    };
  };
  return { key: keyOf("outcomes", sorted, hourly), height: 230, option };
}

/** Horizontal bars ranked high→low with the value printed at the bar end. */
export function rankedBars(
  rows: { label: string; value: number; tooltip?: Record<string, string | number> }[],
  opts: { title: string; format: string },
): AdminChart {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const value = numberFormat(opts.format);
  const option = (dark: boolean): EChartsOption => {
    const t = theme(dark);
    return {
      ...base(t, false, "item"),
      grid: { left: 34, right: 56, top: 18, bottom: 34, containLabel: true },
      tooltip: tooltip(t, "item", {
        formatter: (p: Json) => {
          const r = sorted[Number(p.dataIndex)];
          if (!r) return "";
          const extra = Object.entries(r.tooltip ?? {}).map(([k, v]) => `${k}: ${String(v)}`);
          return [r.label, `${opts.title}: ${value(r.value)}`, ...extra].join("\n");
        },
      }),
      yAxis: axisStyle(t, "", {
        type: "category",
        data: sorted.map((r) => r.label),
        inverse: true,
        splitLine: { show: false },
        axisLabel: { color: t.muted, fontSize: 11, width: 220, overflow: "truncate" },
      }),
      xAxis: axisStyle(t, opts.title, { type: "value", splitNumber: 5, axisLabel: { color: t.muted, fontSize: 11, formatter: value } }),
      series: [
        {
          type: "bar",
          name: opts.title,
          data: sorted.map((r) => r.value),
          color: t.palette[0],
          barMaxWidth: 22,
          itemStyle: { borderRadius: [0, 4, 4, 0] },
          // the value at the bar end, in text ink (never the series colour)
          label: { show: true, position: "right", color: t.text, fontSize: 11, formatter: (p: Json) => value(Number(p.value)) },
        },
      ],
    };
  };
  return { key: keyOf("ranked", sorted, opts), height: Math.min(380, Math.max(100, 30 * sorted.length + 40)), option };
}

/** Cost per day by model: one line per model (fills missing days with 0 per model). */
export function costByModel(rows: { day: string; model_id: string; cost_usd: number }[]): AdminChart {
  return timeSeries(costPoints(rows), "cost (USD)", { money: true });
}

export function costPoints(rows: { day: string; model_id: string; cost_usd: number }[]): Point[] {
  const days = [...new Set(rows.map((r) => r.day))].sort();
  const models = [...new Set(rows.map((r) => r.model_id))].sort();
  const lookup = new Map(rows.map((r) => [`${r.day}|${r.model_id}`, r.cost_usd]));
  return days.flatMap((day) => models.map((model) => ({ x: day, y: lookup.get(`${day}|${model}`) ?? 0, series: model })));
}
