/**
 * Vega-Lite config for EagleEye charts. Specs from the server carry no colours; all styling
 * comes from here so light/dark stay consistent with the rest of the UI.
 *
 * Categorical slots: the dataviz reference palette, in its fixed CVD-safe order, validated
 * (scripts/validate_palette.js) against the app surfaces #ffffff (light) and #0a0a0a (dark):
 * light worst adjacent CVD ΔE 9.1 / normal 19.6; dark 8.4 / 19.3. Three light slots sit
 * below 3:1 on white, so every chart ships with its result table (the relief rule).
 * Hues are assigned in order, never cycled; the server folds series beyond 8 into "Other"
 * and caps scatter colouring at 3 series.
 */

export const CATEGORICAL_LIGHT = [
  "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948",
] as const;

export const CATEGORICAL_DARK = [
  "#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767",
] as const;

/**
 * Sequential (magnitude, e.g. a numeric colour column in a bubble chart): one blue hue from
 * the same reference ramps. Low values recede toward the surface: light steps on white, dark
 * steps on the dark surface; both ends clear 2:1 against their surface.
 */
export const SEQUENTIAL_LIGHT = ["#86b6ef", "#3987e5", "#1c5cab", "#0d366b"] as const;
export const SEQUENTIAL_DARK = ["#184f95", "#2a78d6", "#6da7ec", "#cde2fb"] as const;

const SURFACE_LIGHT = "#ffffff";
const SURFACE_DARK = "#0a0a0a";

/**
 * Status palette (fixed, never themed): reserved for state, never reused as a series colour,
 * and always paired with a label or legend so colour is not the only cue.
 */
export const STATUS = {
  good: "#0ca30c",
  warning: "#fab219",
  critical: "#d03b3b",
  neutral: "#898781",
} as const;

interface Ink {
  primary: string;
  secondary: string;
  muted: string;
  grid: string;
  axis: string;
}

const INK_LIGHT: Ink = {
  primary: "#0b0b0b",
  secondary: "#52514e",
  muted: "#898781",
  grid: "#e1e0d9",
  axis: "#c3c2b7",
};

const INK_DARK: Ink = {
  primary: "#f0efec",
  secondary: "#c3c2b7",
  muted: "#898781",
  grid: "#2c2c2a",
  axis: "#383835",
};

const FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif';

export function chartConfig(dark: boolean): Record<string, unknown> {
  const ink = dark ? INK_DARK : INK_LIGHT;
  const palette = [...(dark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT)];
  const first = palette[0];
  return {
    background: "transparent",
    font: FONT,
    padding: 4,
    autosize: { type: "fit-x", contains: "padding" },
    view: { stroke: null },
    range: { category: palette, ramp: [...(dark ? SEQUENTIAL_DARK : SEQUENTIAL_LIGHT)] },
    axis: {
      labelColor: ink.muted,
      titleColor: ink.secondary,
      labelFontSize: 11,
      titleFontSize: 11,
      titleFontWeight: 500,
      gridColor: ink.grid,
      gridWidth: 1,
      domainColor: ink.axis,
      tickColor: ink.axis,
      labelLimit: 160,
    },
    axisX: { grid: false },
    axisY: { domain: false, ticks: false },
    axisBand: { grid: false },
    legend: {
      labelColor: ink.secondary,
      titleColor: ink.secondary,
      labelFontSize: 11,
      titleFontSize: 11,
      orient: "top",
      symbolType: "circle",
      // size legends have no colour scale: their circles wear muted ink
      symbolFillColor: ink.muted,
      symbolOpacity: 0.6,
    },
    title: { color: ink.primary, fontSize: 13, fontWeight: 600, anchor: "start" },
    // thin marks: 2px lines, ≥8px markers, rounded bar ends, a gap between adjacent bars
    bar: { color: first, cornerRadiusEnd: 3, continuousBandSize: 14 },
    rect: { color: first },
    area: { color: first },
    line: { color: first, strokeWidth: 2 },
    point: { color: first, size: 64, filled: true },
    // bubbles: a 1.5px surface ring keeps overlapping circles apart
    circle: { color: first, stroke: dark ? SURFACE_DARK : SURFACE_LIGHT, strokeWidth: 1.5 },
    // the fitted trend line is reference ink, not a series
    style: { trend: { color: ink.muted, stroke: ink.muted } },
    // text marks (value labels, donut centre) wear text ink, never a series colour
    text: { color: ink.primary, font: FONT },
    arc: { stroke: dark ? "#1a1a19" : "#ffffff", strokeWidth: 2 },
    scale: { bandPaddingInner: 0.25 },
  };
}
