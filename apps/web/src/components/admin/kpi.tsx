"use client";

import type { ReactNode } from "react";

import { Icon, type IconName } from "@/components/admin/icons";
import type { Direction, Tone } from "@/lib/admin-kpi";

const CARD =
  "rounded-xl border border-black/[0.08] bg-white shadow-[0_1px_2px_rgba(0,0,0,0.04)] dark:border-white/10 dark:bg-[#1a1a19]";

/** Inline trend line under a KPI (decorative: the number above is the content). */
export function Sparkline({ values }: { values: readonly (number | null)[] }) {
  const points = values.map((v) => v ?? 0);
  if (points.length < 2) return <div className="h-8" />;
  const max = Math.max(...points, 1e-9);
  const w = 120;
  const h = 32;
  const step = w / (points.length - 1);
  const xy = points.map((v, i) => [i * step, h - 2 - (v / max) * (h - 6)] as const);
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lx, ly] = xy[xy.length - 1];
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true" className="h-8 w-full text-[#2a78d6] dark:text-[#3987e5]">
      <path d={`${line} L${w},${h} L0,${h} Z`} fill="currentColor" opacity={0.1} />
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.75} vectorEffect="non-scaling-stroke" />
      <circle cx={lx} cy={ly} r={2.2} fill="currentColor" />
    </svg>
  );
}

const ARROW: Record<Direction, string> = { up: "▲", down: "▼", flat: "■" };
const TONE: Record<Tone, string> = {
  good: "bg-[#0ca30c]/10 text-[#006300] dark:text-[#0ca30c]",
  bad: "bg-[#d03b3b]/10 text-[#d03b3b] dark:text-[#e66767]",
  neutral: "bg-black/5 text-neutral-600 dark:bg-white/10 dark:text-neutral-300",
};

/** "▲ 12.4%" with the comparison spelled out, so the colour is never the only cue. */
export function DeltaBadge({ text, direction, tone, versus }: {
  text: string;
  direction: Direction;
  tone: Tone;
  versus: string;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px]">
      <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-semibold tabular-nums ${TONE[tone]}`}>
        <span aria-hidden="true" className="text-[8px]">{ARROW[direction]}</span>
        {text}
      </span>
      <span className="text-neutral-500">{versus}</span>
    </span>
  );
}

export function KpiCard({ label, icon, value, delta, hint, trend }: {
  label: string;
  icon: IconName;
  value: string;
  delta?: ReactNode;
  hint?: string;
  trend?: readonly (number | null)[];
}) {
  return (
    <section aria-label={label} className={`${CARD} flex min-w-0 flex-col gap-2 p-3 sm:p-4`}>
      <header className="flex items-center justify-between gap-2">
        <h3 className="truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-neutral-500">{label}</h3>
        <span className="rounded-md bg-[#2a78d6]/10 p-1.5 text-[#2a78d6] dark:text-[#3987e5]">
          <Icon name={icon} className="h-3.5 w-3.5" />
        </span>
      </header>
      <p className="text-[22px] sm:text-[28px] font-semibold leading-none tracking-tight text-neutral-900 dark:text-neutral-50">{value}</p>
      <div className="min-h-[20px]">{delta ?? (hint && <span className="text-[11px] text-neutral-500">{hint}</span>)}</div>
      {delta && hint && <p className="-mt-1 text-[11px] text-neutral-500">{hint}</p>}
      {trend && <Sparkline values={trend} />}
    </section>
  );
}

export type Health = "ok" | "warn" | "bad" | "idle";
const HEALTH: Record<Health, { dot: string; text: string }> = {
  ok: { dot: "bg-[#0ca30c]", text: "text-[#006300] dark:text-[#0ca30c]" },
  warn: { dot: "bg-[#fab219]", text: "text-[#8a5a00] dark:text-[#fab219]" },
  bad: { dot: "bg-[#d03b3b]", text: "text-[#d03b3b] dark:text-[#e66767]" },
  idle: { dot: "bg-neutral-400", text: "text-neutral-500" },
};

/** Live platform signal: a value, a labelled status dot and up to a few detail rows. */
export function StatusCard({ label, icon, value, status, statusText, rows }: {
  label: string;
  icon: IconName;
  value: string;
  status: Health;
  statusText: string;
  rows?: readonly { label: string; value: string; health?: Health }[];
}) {
  return (
    <section aria-label={label} className={`${CARD} flex min-w-0 flex-col gap-3 p-4`}>
      <header className="flex items-center gap-2 text-neutral-500">
        <Icon name={icon} className="h-4 w-4" />
        <h3 className="truncate text-[11px] font-semibold uppercase tracking-[0.08em]">{label}</h3>
      </header>
      <div className="flex items-end justify-between gap-2">
        <p className="text-2xl font-semibold leading-none tracking-tight text-neutral-900 dark:text-neutral-50">{value}</p>
        <span className={`inline-flex items-center gap-1.5 text-xs font-medium ${HEALTH[status].text}`}>
          <span aria-hidden="true" className={`h-2 w-2 rounded-full ${HEALTH[status].dot}`} />
          {statusText}
        </span>
      </div>
      {rows && rows.length > 0 && (
        <ul className="flex flex-col gap-1 border-t border-black/[0.06] pt-2 text-xs dark:border-white/10">
          {rows.map((r) => (
            <li key={r.label} className="flex items-center justify-between gap-2">
              <span className="flex min-w-0 items-center gap-1.5 truncate text-neutral-600 dark:text-neutral-400">
                {r.health && <span aria-hidden="true" className={`h-1.5 w-1.5 shrink-0 rounded-full ${HEALTH[r.health].dot}`} />}
                <span className="truncate">{r.label}</span>
              </span>
              <span className="shrink-0 tabular-nums text-neutral-800 dark:text-neutral-200">{r.value}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export { CARD };
