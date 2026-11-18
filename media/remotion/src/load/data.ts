import data from "../../../public/load-data.json";
import timeline from "../../../public/load-timeline.json";

export const GOLD = "#C5A368";
export const GREEN = "#3ddc84";
export const AMBER = "#ffb347";
export const BLUE = "#5aa9ff";
export const INK = "#f4f1ea";
export const MUTED = "#8a8578";
export const FONT = "Inter, 'Segoe UI', system-ui, sans-serif";
export const MONO = "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace";

export interface Minute {
  minute: number;
  users: number;
  answers: number;
  avg_s: number | null;
  p95_s: number | null;
  error_rate: number;
  tasks: Record<string, number | null>;
  active_answers: number | null;
}
export interface WallClip { name: string; ready: number; asked: number; answered: number; kind: string; answer_s: number }
export interface Part { type: string; at: number; [k: string]: unknown }
export interface LoadScene { n: number; start: number; length: number; parts: Part[] }
export interface LoadTimeline {
  fps: number;
  durationInFrames: number;
  scenes: LoadScene[];
  lines: { id: string; src: string; from: number; frames: number }[];
}

export const DATA = data as unknown as {
  totals: { answers: number; errors: number; avg_s: number; p95_s: number; peak_tasks: Record<string, number> };
  minutes: Minute[];
  walls: WallClip[];
  answers: [number, string, number, number][];
  mosaicSeconds: number;
};
export const TIMELINE = timeline as unknown as LoadTimeline;

// the recorded run's k6 stages (evals/load/chat.js PROFILES.run): [seconds, target users]
const STAGES: [number, number][] = [
  [20, 1], [100, 1], [40, 50], [160, 50], [60, 500], [180, 500],
  [60, 1000], [180, 1000], [120, 2000], [300, 2000], [180, 0],
];

/** Target users t seconds into the run (k6 ramps linearly within a stage). */
export function usersAt(t: number): number {
  let start = 0;
  let prev = 0;
  for (const [seconds, target] of STAGES) {
    if (t <= start + seconds) return Math.round(prev + ((target - prev) * (t - start)) / seconds);
    start += seconds;
    prev = target;
  }
  return 0;
}

/** The last `n` answers finished by run time t (for the k6 log). */
export function answersUpTo(t: number, n: number): [number, string, number, number][] {
  const a = DATA.answers;
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid][0] <= t) lo = mid + 1;
    else hi = mid;
  }
  return a.slice(Math.max(0, lo - n), lo);
}

/** Before → after around a user step: the worst minute and the settled minute. */
export function stepChange(from: number, to: number) {
  const span = DATA.minutes.filter((m) => m.minute >= from && m.minute <= to && m.avg_s !== null);
  const peak = span.reduce((a, b) => ((b.avg_s ?? 0) > (a.avg_s ?? 0) ? b : a));
  const settled = DATA.minutes[to];
  return {
    peak: peak.avg_s ?? 0,
    peakMinute: peak.minute,
    settled: settled.avg_s ?? 0,
    settledMinute: to,
    workersBefore: DATA.minutes[from].tasks["agent-worker"] ?? 1,
    workersAfter: settled.tasks["agent-worker"] ?? 1,
  };
}

export const clamp01 = (v: number) => Math.max(0, Math.min(1, v));
export const fmt = (n: number) => n.toLocaleString("en-US");
