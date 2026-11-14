/** Geometry for the small charts in the admin "usage at a glance" panel (no chart library). */

export interface Point {
  x: number;
  y: number;
}

/**
 * Places values on a w × h canvas, left to right, with `pad` px kept free on every side.
 * All series of one chart share `max`, so they are comparable. Nulls become gaps (NaN y).
 */
export function scalePoints(values: readonly (number | null)[], w: number, h: number, max: number, pad = 6): Point[] {
  const n = values.length;
  const top = max > 0 ? max : 1;
  return values.map((v, i) => ({
    x: n <= 1 ? w / 2 : pad + (i * (w - 2 * pad)) / (n - 1),
    y: v === null ? Number.NaN : h - pad - (Math.max(0, v) / top) * (h - 2 * pad),
  }));
}

/**
 * Smooth line through the points that never overshoots (monotone cubic, Fritsch–Carlson),
 * so a flat stretch stays flat and the curve never dips below zero between two days.
 */
export function monotonePath(points: readonly Point[]): string {
  const p = points.filter((pt) => Number.isFinite(pt.y));
  if (p.length === 0) return "";
  if (p.length === 1) return `M${f(p[0].x)},${f(p[0].y)}`;
  const n = p.length;
  const d: number[] = [];
  for (let i = 0; i < n - 1; i++) d.push((p[i + 1].y - p[i].y) / (p[i + 1].x - p[i].x));
  const m: number[] = [d[0]];
  for (let i = 1; i < n - 1; i++) m.push(d[i - 1] * d[i] <= 0 ? 0 : (d[i - 1] + d[i]) / 2);
  m.push(d[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (d[i] === 0) {
      m[i] = 0;
      m[i + 1] = 0;
      continue;
    }
    const a = m[i] / d[i];
    const b = m[i + 1] / d[i];
    const s = a * a + b * b;
    if (s > 9) {
      const t = 3 / Math.sqrt(s);
      m[i] = t * a * d[i];
      m[i + 1] = t * b * d[i];
    }
  }
  let path = `M${f(p[0].x)},${f(p[0].y)}`;
  for (let i = 0; i < n - 1; i++) {
    const dx = (p[i + 1].x - p[i].x) / 3;
    path += ` C${f(p[i].x + dx)},${f(p[i].y + m[i] * dx)} ${f(p[i + 1].x - dx)},${f(p[i + 1].y - m[i + 1] * dx)} ${f(p[i + 1].x)},${f(p[i + 1].y)}`;
  }
  return path;
}

const f = (v: number): string => (Math.round(v * 10) / 10).toString();

/** Index of the bucket nearest to x (for hover), given n buckets laid out by scalePoints. */
export function nearestIndex(x: number, w: number, n: number, pad = 6): number {
  if (n <= 1) return 0;
  const i = Math.round(((x - pad) / (w - 2 * pad)) * (n - 1));
  return Math.min(n - 1, Math.max(0, i));
}

export type BudgetState = "good" | "warning" | "critical";

/** Spend bar colour: within budget, past the first alert, past the last alert. */
export function budgetState(usedFraction: number | null, alerts: readonly number[]): BudgetState {
  if (usedFraction === null) return "good";
  const sorted = [...alerts].sort((a, b) => a - b);
  if (sorted.length && usedFraction >= sorted[sorted.length - 1]) return "critical";
  if (sorted.length && usedFraction >= sorted[0]) return "warning";
  return "good";
}

/** Per-bucket ratio, e.g. cache hits / lookups (null where the denominator is 0). */
export function ratios(numerators: readonly number[], denominators: readonly number[]): (number | null)[] {
  return numerators.map((n, i) => (denominators[i] > 0 ? n / denominators[i] : null));
}
