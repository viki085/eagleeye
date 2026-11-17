"use client";

import { DeltaBadge } from "@/components/admin/kpi";
import { ChartPanel, Panel } from "@/components/admin/parts";
import { timeSeries } from "@/lib/admin-charts";
import { bucketLabel, count } from "@/lib/admin-format";
import { compare } from "@/lib/admin-kpi";
import { STEP_GROUPS, stepGroupLabel } from "@/lib/admin-labels";
import type { AdminOverview } from "@/lib/api";

type TrendRow = AdminOverview["step_trend"][number];

function duration(ms: number | null): string {
  if (ms === null) return "—";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

/** Mean duration of each major pipeline stage over time (sub-steps omitted to stay readable). */
export function StepLatencyTrend({ d, hourly }: { d: AdminOverview; hourly: boolean }) {
  const order = STEP_GROUPS.map((g) => g.label);
  return (
    <ChartPanel
      className="xl:col-span-8"
      title="Step latency trend"
      subtitle={`Mean duration of each major pipeline stage per ${hourly ? "hour" : "day"} (UTC) · sub-steps omitted`}
      chart={timeSeries(
        d.step_trend.map((p) => ({ x: p.bucket, y: Math.round(p.avg_ms) / 1000, series: stepGroupLabel(p.step) })),
        "avg seconds",
        {
          hourly,
          seriesOrder: order,
          format: ".1f",
          domain: d.series.length ? [d.series[0].bucket, d.series[d.series.length - 1].bucket] : undefined,
        },
      )}
      rows={d.step_trend}
      columns={[
        { key: "b", label: hourly ? "Hour (UTC)" : "Day", render: (r: TrendRow) => bucketLabel(r.bucket, hourly) },
        { key: "s", label: "Stage", render: (r: TrendRow) => stepGroupLabel(r.step) },
        { key: "n", label: "Executions", numeric: true, render: (r: TrendRow) => count(r.executions) },
        { key: "avg", label: "Avg", numeric: true, render: (r: TrendRow) => duration(r.avg_ms) },
      ]}
    />
  );
}

const VERSUS = { "24h": "vs prev. 24 h", "7d": "vs prev. 7 days", "14d": "vs prev. 14 days", "30d": "vs prev. 30 days" } as const;

/** This period's mean per stage against the previous period, slowest first. */
export function StepLatencyChange({ d }: { d: AdminOverview }) {
  const rows = [...d.step_change].sort((a, b) => (b.avg_ms ?? 0) - (a.avg_ms ?? 0));
  return (
    <Panel className="xl:col-span-4" title="Step latency change" subtitle={`Mean duration per stage ${VERSUS[d.range]}`}>
      {rows.length === 0 ? (
        <p className="py-6 text-center text-xs text-neutral-400">No pipeline activity in this period.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-black/[0.06] dark:divide-white/[0.08]">
          {rows.map((r) => {
            const c = compare(r.avg_ms, r.prev_avg_ms, "down");
            return (
              <li key={r.step} className="flex items-center justify-between gap-3 py-2.5">
                <div className="min-w-0">
                  <p className="truncate text-[13px] font-medium">{stepGroupLabel(r.step)}</p>
                  <p className="text-[11px] text-neutral-500">
                    {count(r.executions)} runs · was {duration(r.prev_avg_ms)}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <span className="text-sm font-semibold tabular-nums">{duration(r.avg_ms)}</span>
                  {c ? (
                    <DeltaBadge text={`${c.pct > 0 ? "+" : ""}${c.pct}%`} direction={c.direction} tone={c.tone} versus="" />
                  ) : (
                    <span className="text-[11px] text-neutral-400">no baseline</span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
