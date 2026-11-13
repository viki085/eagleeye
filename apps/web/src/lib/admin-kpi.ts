/** Period-over-period comparisons for the Overview's KPI cards. */

export type Better = "up" | "down";
export type Direction = "up" | "down" | "flat";
export type Tone = "good" | "bad" | "neutral";

const FLAT_PCT = 0.5; // moves smaller than this read as "no change"
const FLAT_POINTS = 0.1;

function toneOf(direction: Direction, better: Better): Tone {
  if (direction === "flat") return "neutral";
  return direction === better ? "good" : "bad";
}

/** Relative change of a count or amount; null when there is no baseline to compare with. */
export function compare(
  current: number | null,
  previous: number | null,
  better: Better,
): { pct: number; direction: Direction; tone: Tone } | null {
  if (current === null || previous === null || previous === 0) return null;
  const pct = Math.round(((current - previous) / previous) * 1000) / 10;
  const direction: Direction = Math.abs(pct) < FLAT_PCT ? "flat" : pct > 0 ? "up" : "down";
  return { pct, direction, tone: toneOf(direction, better) };
}

/** Change of a rate (0..1) in percentage points: 90% → 95% is +5 pts, not +5.6%. */
export function rateDelta(
  current: number | null,
  previous: number | null,
  better: Better,
): { points: number; direction: Direction; tone: Tone } | null {
  if (current === null || previous === null) return null;
  const points = Math.round((current - previous) * 1000) / 10;
  const direction: Direction = Math.abs(points) < FLAT_POINTS ? "flat" : points > 0 ? "up" : "down";
  return { points, direction, tone: toneOf(direction, better) };
}
