import React from "react";
import { BLUE, DATA, FONT, GOLD, INK, MUTED, clamp01, fmt, stepChange } from "./data";

const LAST_MINUTE = 23;
const PLOT_W = 1500;
const LEFT = 250;

type Pt = [number, number];
const x = (minute: number) => LEFT + (minute / LAST_MINUTE) * PLOT_W;

function line(points: Pt[], y0: number, h: number, max: number, step = false): string {
  const y = (v: number) => y0 + h - (v / max) * h;
  return points
    .map(([m, v], i) => {
      if (i === 0) return `M${x(m)},${y(v)}`;
      return step ? `H${x(m)}V${y(v)}` : `L${x(m)},${y(v)}`;
    })
    .join("");
}

/** A small panel: title, max label, a baseline and one series up to `upTo` minutes. */
const Panel: React.FC<{
  title: string; unit: string; y0: number; h: number; max: number; color: string;
  points: Pt[]; upTo: number; step?: boolean; dashed?: Pt[]; opacity?: number; ticks: number[];
}> = ({ title, unit, y0, h, max, color, points, upTo, step, dashed, opacity = 1, ticks }) => {
  const shown = points.filter(([m]) => m <= upTo);
  const dash = dashed?.filter(([m]) => m <= upTo) ?? [];
  return (
    <g opacity={opacity}>
      <text x={60} y={y0 + 18} fill={INK} fontSize={26} fontWeight={600} fontFamily={FONT}>{title}</text>
      <text x={60} y={y0 + 50} fill={MUTED} fontSize={20} fontFamily={FONT}>{unit}</text>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={LEFT} x2={LEFT + PLOT_W} y1={y0 + h - (v / max) * h} y2={y0 + h - (v / max) * h} stroke="#ffffff14" />
          <text x={LEFT - 14} y={y0 + h - (v / max) * h + 6} fill={MUTED} fontSize={18} textAnchor="end" fontFamily={FONT}>{fmt(v)}</text>
        </g>
      ))}
      {dash.length > 1 && <path d={line(dash, y0, h, max)} fill="none" stroke={color} strokeOpacity={0.45} strokeWidth={2} strokeDasharray="6 6" />}
      {shown.length > 1 && <path d={line(shown, y0, h, max, step)} fill="none" stroke={color} strokeWidth={3} strokeLinejoin="round" />}
    </g>
  );
};

const series = (key: (m: (typeof DATA.minutes)[number]) => number | null): Pt[] =>
  DATA.minutes.filter((m) => m.minute <= LAST_MINUTE && key(m) !== null).map((m) => [m.minute, key(m) as number]);
const USERS = series((m) => m.users);
const WORKERS = series((m) => m.tasks["agent-worker"]);
const AVG = series((m) => (m.answers > 0 ? m.avg_s : null));
const P95 = series((m) => (m.answers > 0 ? m.p95_s : null));

const Axis: React.FC<{ y: number }> = ({ y }) => (
  <g>
    {[0, 5, 10, 15, 20].map((m) => (
      <text key={m} x={x(m)} y={y} fill={MUTED} fontSize={18} textAnchor="middle" fontFamily={FONT}>{`${m} min`}</text>
    ))}
  </g>
);

/** Before → after label on the response-time panel for one user step. */
const StepLabel: React.FC<{ from: number; to: number; label: string; y0: number; h: number; max: number; opacity: number }> = ({ from, to, label, y0, h, max, opacity }) => {
  const c = stepChange(from, to);
  const px = x(c.peakMinute);
  const py = y0 + h - (c.peak / max) * h;
  return (
    <g opacity={opacity}>
      <circle cx={px} cy={py} r={7} fill={BLUE} stroke="#0b0b0b" strokeWidth={2} />
      <text x={px + 14} y={py - 12} fill={INK} fontSize={22} fontWeight={600} fontFamily={FONT}>
        {`${label}: ${c.peak.toFixed(1)} s → ${c.settled.toFixed(1)} s`}
      </text>
      <text x={px + 14} y={py + 14} fill={MUTED} fontSize={19} fontFamily={FONT}>{`workers ${c.workersBefore} → ${c.workersAfter}`}</text>
    </g>
  );
};

const STEPS: [number, number, string][] = [[6, 9, "500 users"], [10, 13, "1,000 users"], [15, 18, "2,000 users"]];

/**
 * Users, agent workers and response time on one time axis (three panels, one scale each).
 * `upTo` reveals the run up to that minute; `reveal` (0-1 per panel) builds the summary in turn.
 */
export const ScalingChart: React.FC<{ upTo: number; reveal?: [number, number, number]; labels: number; title: string }> = ({ upTo, reveal = [1, 1, 1], labels, title }) => (
  <svg width={1920} height={1080} viewBox="0 0 1920 1080">
    <rect width={1920} height={1080} fill="#0b0b0a" />
    <text x={60} y={92} fill={GOLD} fontSize={22} letterSpacing={5} fontFamily={FONT}>LOAD TEST · MEASURED</text>
    <text x={60} y={140} fill={INK} fontSize={44} fontWeight={700} fontFamily={FONT}>{title}</text>
    <Panel title="Users" unit="simulated, k6" y0={200} h={190} max={2000} color="#d9d4c7" points={USERS} upTo={upTo} opacity={reveal[0]} ticks={[0, 1000, 2000]} />
    <Panel title="Agent workers" unit="running tasks" y0={450} h={190} max={12} color={GOLD} points={WORKERS} upTo={upTo} step opacity={reveal[1]} ticks={[0, 6, 12]} />
    <Panel title="Response time" unit="avg (solid) · p95 (dashed), seconds" y0={700} h={250} max={45} color={BLUE} points={AVG} dashed={P95} upTo={upTo} opacity={reveal[2]} ticks={[0, 15, 30, 45]} />
    {STEPS.slice(0, labels).map(([a, b, l]) => (
      <StepLabel key={l} from={a} to={b} label={l} y0={700} h={250} max={45} opacity={reveal[2] * clamp01((upTo - b) / 0.6)} />
    ))}
    <Axis y={1000} />
  </svg>
);

/** The headline figures row (summary scene). */
export const Headlines: React.FC<{ opacity: number }> = ({ opacity }) => {
  const t = DATA.totals;
  const success = (100 * (1 - t.errors / t.answers)).toFixed(2);
  const items = [
    ["2,000", "peak users"],
    [fmt(t.answers), "answers"],
    [`${success}%`, "succeeded"],
    [`${t.peak_tasks["agent-worker"]}`, "peak agent workers"],
  ];
  return (
    <div style={{ position: "absolute", right: 60, top: 104, display: "flex", gap: 44, opacity, fontFamily: FONT }}>
      {items.map(([v, l]) => (
        <div key={l} style={{ color: INK, fontSize: 26 }}>
          <span style={{ fontWeight: 700, color: GOLD, marginRight: 10 }}>{v}</span>
          <span style={{ color: MUTED }}>{l}</span>
        </div>
      ))}
    </div>
  );
};
