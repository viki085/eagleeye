/**
 * Server chart spec (the constrained Vega-Lite the API builds, see packages/charts) → an ECharts
 * option. Every number still comes from the server's data; this only changes how it is drawn.
 * Pure (no ECharts import), so it is unit-tested. Returns null for any shape it doesn't know,
 * and the card then falls back to the Vega renderer, so a new server chart type never breaks.
 * Tooltips use ECharts' rich-text mode (drawn on the canvas, not HTML), so text from a user's
 * data can't inject markup.
 */

import { CATEGORICAL_DARK, CATEGORICAL_LIGHT, SEQUENTIAL_DARK, SEQUENTIAL_LIGHT } from "./chart-theme";

type Json = Record<string, unknown>;
type Row = Record<string, unknown>;
export type EChartsOption = Json;

const LONG_SERIES = 40; // more points than this: add a zoom slider under the chart

interface Theme {
  palette: readonly string[];
  ramp: readonly string[];
  text: string;
  muted: string;
  grid: string;
  axis: string;
  surface: string;
}

function theme(dark: boolean): Theme {
  return dark
    ? { palette: CATEGORICAL_DARK, ramp: SEQUENTIAL_DARK, text: "#f0efec", muted: "#c3c2b7", grid: "#2c2c2a", axis: "#383835", surface: "#141413" }
    : { palette: CATEGORICAL_LIGHT, ramp: SEQUENTIAL_LIGHT, text: "#0b0b0b", muted: "#52514e", grid: "#e1e0d9", axis: "#c3c2b7", surface: "#ffffff" };
}

const obj = (v: unknown): Json => (v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : {});
const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function fmt(v: unknown): string {
  const n = num(v);
  if (n === null) return String(v ?? "");
  return Math.abs(n) >= 1000 || Number.isInteger(n)
    ? n.toLocaleString("en-US", { maximumFractionDigits: 2 })
    : n.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

function axisStyle(t: Theme, name: string, extra: Json = {}): Json {
  return {
    name,
    nameLocation: "middle",
    nameGap: 34,
    nameTextStyle: { color: t.muted, fontSize: 11 },
    axisLine: { lineStyle: { color: t.axis } },
    axisTick: { show: false },
    axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true },
    splitLine: { lineStyle: { color: t.grid, type: "dashed" } },
    ...extra,
  };
}

function base(t: Theme, legend: boolean, trigger: "axis" | "item"): Json {
  return {
    color: [...t.palette],
    backgroundColor: "transparent",
    textStyle: { fontFamily: "inherit", color: t.text },
    animationDuration: 600,
    animationEasing: "cubicOut",
    grid: { left: 34, right: 20, top: legend ? 40 : 18, bottom: 34, containLabel: true },
    legend: legend ? { top: 0, type: "scroll", textStyle: { color: t.muted, fontSize: 11 }, icon: "roundRect", itemWidth: 12, itemHeight: 8 } : { show: false },
    tooltip: {
      trigger,
      renderMode: "richText", // canvas text, never HTML from the data
      backgroundColor: t.surface,
      borderColor: t.axis,
      textStyle: { color: t.text, fontSize: 12 },
      valueFormatter: (v: unknown) => fmt(v),
      ...(trigger === "axis" ? { axisPointer: { type: "shadow", shadowStyle: { color: "rgba(127,127,127,0.08)" } } } : {}),
    },
  };
}

function seriesNames(rows: Row[]): (string | null)[] {
  const seen: (string | null)[] = [];
  for (const r of rows) {
    const s = r.series === null || r.series === undefined ? null : String(r.series);
    if (!seen.includes(s)) seen.push(s);
  }
  return seen;
}

function gradient(color: string): Json {
  return {
    type: "linear", x: 0, y: 0, x2: 0, y2: 1,
    colorStops: [{ offset: 0, color: `${color}66` }, { offset: 1, color: `${color}05` }],
  };
}

// ---- bars -----------------------------------------------------------------------------------

function bars(rows: Row[], enc: Json, t: Theme, mark: Json): EChartsOption | null {
  const horizontal = obj(enc.y).type === "nominal";
  const cat = obj(horizontal ? enc.y : enc.x);
  const val = obj(horizontal ? enc.x : enc.y);
  const order = Array.isArray(cat.sort) ? (cat.sort as unknown[]).map(String) : [...new Set(rows.map((r) => String(r.x)))];
  const names = seriesNames(rows);
  const grouped = Boolean(enc.xOffset || enc.yOffset);
  const radius = num(mark.cornerRadiusEnd) ?? 3;
  const series = names.map((name, i) => {
    const mine = rows.filter((r) => String(r.series ?? "") === String(name ?? ""));
    const byCat = new Map(mine.map((r) => [String(r.x), num(r.y)]));
    const last = i === names.length - 1;
    return {
      type: "bar",
      name: name ?? str(val.title),
      data: order.map((c) => byCat.get(c) ?? null),
      ...(grouped || names.length === 1 ? {} : { stack: "total" }),
      barMaxWidth: 46,
      emphasis: { focus: "series" },
      itemStyle: {
        borderRadius: grouped || names.length === 1 || last ? (horizontal ? [0, radius + 2, radius + 2, 0] : [radius + 2, radius + 2, 0, 0]) : 0,
      },
    };
  });
  const catAxis = axisStyle(t, str(cat.title), { type: "category", data: order, splitLine: { show: false }, axisLabel: { color: t.muted, fontSize: 11, hideOverlap: true, ...(horizontal ? {} : { interval: "auto" }) } });
  const valAxis = axisStyle(t, str(val.title), { type: "value" });
  return {
    ...base(t, names.length > 1, "axis"),
    ...(horizontal ? { yAxis: { ...catAxis, inverse: true, nameGap: 0, name: "" }, xAxis: valAxis } : { xAxis: catAxis, yAxis: { ...valAxis, nameGap: 46 } }),
    series,
  };
}

function histogram(rows: Row[], enc: Json, t: Theme): EChartsOption {
  const labels = rows.map((r) => `${fmt(r.x)}–${fmt(r.x2)}`);
  return {
    ...base(t, false, "axis"),
    xAxis: axisStyle(t, str(obj(enc.x).title), { type: "category", data: labels, splitLine: { show: false } }),
    yAxis: axisStyle(t, str(obj(enc.y).title) || "count", { type: "value", minInterval: 1, nameGap: 40 }),
    series: [{ type: "bar", name: "count", data: rows.map((r) => num(r.y)), barCategoryGap: "4%", itemStyle: { borderRadius: [3, 3, 0, 0] } }],
  };
}

// ---- lines and areas ------------------------------------------------------------------------

function lines(rows: Row[], enc: Json, t: Theme, area: boolean): EChartsOption | null {
  const x = obj(enc.x);
  const xType = x.type === "temporal" ? "time" : x.type === "quantitative" ? "value" : "category";
  const years = obj(x.axis).format === "d";
  const names = seriesNames(rows);
  const many = rows.length / Math.max(names.length, 1) > LONG_SERIES;
  const series = names.map((name, i) => {
    const points = rows.filter((r) => String(r.series ?? "") === String(name ?? "")).map((r) => [r.x, num(r.y)]);
    const color = t.palette[i % t.palette.length];
    return {
      type: "line",
      name: name ?? str(obj(enc.y).title),
      data: points,
      smooth: 0.25,
      showSymbol: !many,
      symbolSize: 6,
      lineStyle: { width: 2.5 },
      emphasis: { focus: "series" },
      ...(area ? { areaStyle: { color: gradient(color) } } : {}),
    };
  });
  const xAxis = axisStyle(t, str(x.title), {
    type: xType,
    splitLine: { show: false },
    ...(xType === "category" ? { data: [...new Set(rows.map((r) => String(r.x)))], boundaryGap: false } : {}),
    ...(xType === "value" ? { scale: true } : {}),
    ...(years ? { minInterval: 1, axisLabel: { color: t.muted, fontSize: 11, formatter: (v: number) => String(Math.round(v)) } } : {}),
  });
  return {
    ...base(t, names.length > 1, "axis"),
    xAxis,
    yAxis: axisStyle(t, str(obj(enc.y).title), { type: "value", nameGap: 46, scale: !area }),
    ...(many ? { dataZoom: [{ type: "inside" }, { type: "slider", height: 18, bottom: 0, borderColor: t.axis }], grid: { left: 34, right: 20, top: names.length > 1 ? 40 : 18, bottom: 56, containLabel: true } } : {}),
    tooltip: { ...obj(base(t, false, "axis").tooltip), axisPointer: { type: "line", lineStyle: { color: t.axis } } },
    series,
  };
}

// ---- scatter --------------------------------------------------------------------------------

function scatter(spec: Json, t: Theme): EChartsOption | null {
  const layers = Array.isArray(spec.layer) ? (spec.layer as Json[]) : [];
  const points = layers.find((l) => l.name === "points") ?? layers.find((l) => obj(l.mark).type === "circle");
  if (!points) return null;
  const rows = (obj(spec.data).values as Row[] | undefined) ?? [];
  const enc = obj(points.encoding);
  const color = obj(enc.color);
  const size = obj(enc.size);
  const labelTitle = (Array.isArray(enc.tooltip) ? (enc.tooltip as Json[]) : []).find((f) => f.field === "label")?.title;
  const sizes = rows.map((r) => num(r.size)).filter((v): v is number => v !== null);
  const [lo, hi] = [Math.min(...sizes), Math.max(...sizes)];
  const radius = (v: unknown): number => {
    const n = num(v);
    if (n === null || !sizes.length || hi === lo) return 12;
    return 8 + Math.sqrt((n - lo) / (hi - lo)) * 30;
  };
  const point = (r: Row) => [r.x, r.y, r.size ?? null, r.series ?? null, r.label ?? null];
  const quantColor = color.type === "quantitative";
  const groups = color.type === "nominal" ? seriesNames(rows) : [null];
  const series: Json[] = groups.map((g) => ({
    type: "scatter",
    name: g ?? str(obj(enc.y).title),
    data: rows.filter((r) => color.type !== "nominal" || String(r.series ?? "") === String(g ?? "")).map(point),
    symbolSize: (d: unknown[]) => (enc.size ? radius(d[2]) : 10),
    itemStyle: { opacity: 0.82, borderColor: t.surface, borderWidth: 1 },
    emphasis: { focus: "series", scale: 1.15 },
  }));
  const trend = layers.find((l) => l.name === "trend");
  const trendRows = (obj(trend?.data).values as Row[] | undefined) ?? [];
  if (trendRows.length >= 2) {
    series.push({
      type: "line", name: "trend", data: trendRows.map((r) => [r.x, r.y]), symbol: "none", silent: true,
      lineStyle: { type: "dashed", width: 1.5, color: t.muted }, tooltip: { show: false }, z: 1,
    });
  }
  const tip = (p: Json): string => {
    const d = (p.data as unknown[]) ?? [];
    const lines = [
      labelTitle && d[4] !== null ? `${labelTitle}: ${String(d[4])}` : "",
      `${str(obj(enc.x).title)}: ${fmt(d[0])}`,
      `${str(obj(enc.y).title)}: ${fmt(d[1])}`,
      enc.size && d[2] !== null ? `${str(size.title)}: ${fmt(d[2])}` : "",
      enc.color && d[3] !== null ? `${str(color.title)}: ${fmt(d[3])}` : "",
    ];
    return lines.filter(Boolean).join("\n");
  };
  const values = rows.map((r) => num(r.series)).filter((v): v is number => v !== null);
  return {
    ...base(t, color.type === "nominal" && groups.length > 1, "item"),
    tooltip: { ...obj(base(t, false, "item").tooltip), formatter: tip },
    xAxis: axisStyle(t, str(obj(enc.x).title), { type: "value", scale: true }),
    yAxis: axisStyle(t, str(obj(enc.y).title), { type: "value", scale: true, nameGap: 46 }),
    ...(quantColor && values.length
      ? {
          visualMap: {
            type: "continuous", dimension: 3, seriesIndex: 0, min: Math.min(...values), max: Math.max(...values),
            inRange: { color: [...t.ramp] }, orient: "horizontal", left: "center", top: 0, itemHeight: 90, itemWidth: 10,
            text: [fmt(Math.max(...values)), `${str(color.title)}  ${fmt(Math.min(...values))}`], textStyle: { color: t.muted, fontSize: 11 }, calculable: false,
          },
          grid: { left: 34, right: 20, top: 44, bottom: 34, containLabel: true },
        }
      : {}),
    series,
  };
}

/** The ECharts option for a server chart spec, or null to fall back to Vega. */
export function toEChartsOption(spec: Record<string, unknown>, dark: boolean): EChartsOption | null {
  try {
    const t = theme(dark);
    if (Array.isArray(spec.layer)) return scatter(spec, t);
    const rows = obj(spec.data).values;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const mark = obj(spec.mark);
    const enc = obj(spec.encoding);
    const type = str(mark.type) || str(spec.mark);
    if (type === "bar" && enc.x2) return histogram(rows as Row[], enc, t);
    if (type === "bar") return bars(rows as Row[], enc, t, mark);
    if (type === "line" || type === "area") return lines(rows as Row[], enc, t, type === "area");
    return null;
  } catch {
    return null;
  }
}

/** Height in px the server asked for (default 280). */
export function chartHeight(spec: Record<string, unknown>): number {
  return num(spec.height) ?? 280;
}
