/**
 * Vega-Lite specs for the admin console, built from API data. No colours here: the theme in
 * lib/chart-theme.ts applies the validated palette. Lines for time series, horizontal bars for
 * categories; one axis per chart (never dual-axis).
 */

import { STATUS } from "./chart-theme";

export type Spec = Record<string, unknown>;

interface Point {
  x: string;
  y: number;
  series?: string;
}

export function timeSeries(
  points: Point[],
  yTitle: string,
  opts: { money?: boolean; hourly?: boolean } = {},
): Spec {
  const multi = points.some((p) => p.series !== undefined);
  return {
    data: { values: points },
    mark: { type: "line", point: points.length <= 40, tooltip: true },
    encoding: {
      // buckets are UTC hours/days: a UTC scale keeps ticks on bucket boundaries in any timezone
      x: {
        field: "x",
        type: "temporal",
        title: null,
        scale: { type: "utc" },
        // ticks on whole buckets: one per day (or every 3 hours), never several inside one day
        axis: {
          format: opts.hourly ? "%H:%M" : "%d %b",
          labelAngle: 0,
          // Vega interval names: "hours" (plural), "day"; an unknown name crashes the render
          tickCount: opts.hourly ? { interval: "hours", step: 3 } : { interval: "day", step: 1 },
        },
      },
      y: {
        field: "y",
        type: "quantitative",
        title: yTitle,
        ...(opts.money ? { axis: { format: "$,.2f" } } : {}),
      },
      ...(multi ? { color: { field: "series", type: "nominal", title: null } } : {}),
    },
    width: "container",
    height: 200,
  };
}

export function categoryBars(rows: { label: string; value: number }[], xTitle: string): Spec {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  return {
    data: { values: sorted },
    mark: { type: "bar", tooltip: true, cornerRadiusEnd: 3 },
    encoding: {
      y: { field: "label", type: "nominal", sort: sorted.map((r) => r.label), title: null },
      // category bars are counts: whole-number ticks only
      x: {
        field: "value",
        type: "quantitative",
        title: xTitle,
        axis: { tickMinStep: 1, format: "d", tickCount: 6 },
      },
    },
    width: "container",
    height: Math.min(360, Math.max(80, 26 * sorted.length)),
  };
}

/**
 * Part-to-whole donut (≤ 6 slices; the server folds the rest into "Other"). Colours follow the
 * entity: the domain is sorted by label, so a model keeps its colour when the period changes.
 */
export function donut(
  rows: { label: string; value: number }[],
  centre: { value: string; caption: string },
  opts: { money?: boolean } = {},
): Spec {
  const total = rows.reduce((sum, r) => sum + r.value, 0);
  const values = rows.map((r) => ({ ...r, share: total ? r.value / total : 0 }));
  const domain = [...rows.map((r) => r.label)].sort((a, b) => (a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)));
  const valueFormat = opts.money ? "$,.4f" : ",d";
  return {
    data: { values },
    layer: [
      {
        mark: { type: "arc", innerRadius: 64, outerRadius: 100, padAngle: 0.015, cornerRadius: 3 },
        encoding: {
          theta: { field: "value", type: "quantitative", stack: true },
          color: {
            field: "label",
            type: "nominal",
            scale: { domain },
            legend: { orient: "right", title: null, labelLimit: 180 },
          },
          order: { field: "value", type: "quantitative", sort: "descending" },
          tooltip: [
            { field: "label", type: "nominal", title: "Model" },
            { field: "value", type: "quantitative", title: opts.money ? "Cost" : "Value", format: valueFormat },
            { field: "share", type: "quantitative", title: "Share", format: ".1%" },
          ],
        },
      },
      {
        data: { values: [{}] },
        mark: { type: "text", fontSize: 20, fontWeight: 600, dy: -8 },
        encoding: { text: { value: centre.value } },
      },
      {
        data: { values: [{}] },
        mark: { type: "text", fontSize: 11, dy: 12, opacity: 0.7 },
        encoding: { text: { value: centre.caption } },
      },
    ],
    width: "container",
    height: 220,
  };
}

/** Requests per bucket split by outcome, in the fixed status colours (with a legend). */
export function outcomeBars(
  points: { bucket: string; succeeded: number; failed: number; other: number }[],
  hourly: boolean,
): Spec {
  const values = points.flatMap((p) => [
    { x: p.bucket, outcome: "Succeeded", requests: p.succeeded },
    { x: p.bucket, outcome: "Failed", requests: p.failed },
    { x: p.bucket, outcome: "Cancelled / in progress", requests: p.other },
  ]);
  return {
    data: { values },
    // 70% of the bucket: a visible gap between adjacent periods
    mark: { type: "bar", tooltip: true, cornerRadiusEnd: 0, width: { band: 0.7 } },
    encoding: {
      x: {
        field: "x",
        type: "temporal",
        title: null,
        timeUnit: hourly ? "utcyearmonthdatehours" : "utcyearmonthdate",
        axis: { format: hourly ? "%H:%M" : "%d %b", labelAngle: 0, labelOverlap: "greedy" },
      },
      y: { field: "requests", type: "quantitative", stack: true, title: "requests", axis: { tickMinStep: 1, format: "d" } },
      color: {
        field: "outcome",
        type: "nominal",
        scale: {
          domain: ["Succeeded", "Failed", "Cancelled / in progress"],
          range: [STATUS.good, STATUS.critical, STATUS.neutral],
        },
        legend: { title: null },
      },
      order: { field: "outcome", sort: "descending" },
    },
    width: "container",
    height: 220,
  };
}

/** Horizontal bars ranked high→low with the value printed at the bar end. */
export function rankedBars(
  rows: { label: string; value: number; tooltip?: Record<string, string | number> }[],
  opts: { title: string; format: string },
): Spec {
  const sorted = [...rows].sort((a, b) => b.value - a.value);
  const values = sorted.map((r) => ({ label: r.label, value: r.value, ...(r.tooltip ?? {}) }));
  const extra = Object.keys(sorted[0]?.tooltip ?? {}).map((field) => ({ field, type: "nominal" }));
  const y = { field: "label", type: "nominal", sort: sorted.map((r) => r.label), title: null, axis: { labelLimit: 220 } };
  return {
    data: { values },
    encoding: { y },
    layer: [
      {
        mark: { type: "bar", cornerRadiusEnd: 3 },
        encoding: {
          x: { field: "value", type: "quantitative", title: opts.title, axis: { tickCount: 5, format: opts.format } },
          tooltip: [
            { field: "label", type: "nominal", title: "Name" },
            { field: "value", type: "quantitative", title: opts.title, format: opts.format },
            ...extra,
          ],
        },
      },
      {
        mark: { type: "text", align: "left", dx: 4, fontSize: 11 },
        encoding: {
          x: { field: "value", type: "quantitative" },
          text: { field: "value", type: "quantitative", format: opts.format },
        },
      },
    ],
    width: "container",
    height: Math.min(380, Math.max(90, 28 * sorted.length)),
  };
}

/** Cost per day by model: one line per model (fills missing days with 0 per model). */
export function costByModel(rows: { day: string; model_id: string; cost_usd: number }[]): Spec {
  const days = [...new Set(rows.map((r) => r.day))].sort();
  const models = [...new Set(rows.map((r) => r.model_id))].sort();
  const lookup = new Map(rows.map((r) => [`${r.day}|${r.model_id}`, r.cost_usd]));
  const points = days.flatMap((day) =>
    models.map((model) => ({ x: day, y: lookup.get(`${day}|${model}`) ?? 0, series: model })),
  );
  return timeSeries(points, "cost (USD)", { money: true });
}
