/**
 * Vega-Lite specs for the admin console, built from API data. No colours here: the theme in
 * lib/chart-theme.ts applies the validated palette. Lines for time series, horizontal bars for
 * categories; one axis per chart (never dual-axis).
 */

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
