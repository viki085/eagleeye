"use client";

import { ChartPanel, SectionState, StatTile } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { timeSeries } from "@/lib/admin-charts";
import { bucketLabel, count, money, pct, seconds } from "@/lib/admin-format";
import type { AdminRange, AdminSeriesPoint, ApiClient } from "@/lib/api";

export function OverviewTab({ api, range }: { api: ApiClient; range: AdminRange }) {
  const [state] = useAdminData(() => api.adminOverview(range), [api, range]);
  const hourly = range === "24h";
  const columns = [
    { key: "bucket", label: hourly ? "Hour (UTC)" : "Day", render: (r: AdminSeriesPoint) => bucketLabel(r.bucket, hourly) },
    { key: "runs", label: "Answers", numeric: true, render: (r: AdminSeriesPoint) => count(r.runs) },
    { key: "users", label: "Users", numeric: true, render: (r: AdminSeriesPoint) => count(r.users) },
    { key: "failed", label: "Failed", numeric: true, render: (r: AdminSeriesPoint) => count(r.failed) },
    { key: "cost", label: "Cost", numeric: true, render: (r: AdminSeriesPoint) => money(r.cost_usd) },
  ];
  return (
    <SectionState state={state}>
      {(d) => (
        <div className="flex flex-col gap-3">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatTile label="Active users" value={count(d.active_users)} />
            <StatTile label="Answers" value={count(d.runs)} hint={`${pct(d.succeeded, d.runs)} succeeded`} />
            <StatTile
              label="Failed"
              value={pct(d.failed, d.runs)}
              hint={`${count(d.failed)} failed · ${count(d.cancelled)} stopped · ${count(d.degraded)} degraded`}
            />
            <StatTile label="LLM cost" value={money(d.cost_usd)} hint={`${money(d.cost_per_run_usd, 4)} per answer`} />
            <StatTile label="Time to first word" value={seconds(d.p50_ttft_s)} hint={`p95 ${seconds(d.p95_ttft_s)}`} />
            <StatTile label="Answer time" value={seconds(d.p50_duration_s)} hint={`p95 ${seconds(d.p95_duration_s)}`} />
          </div>
          <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
            <ChartPanel
              title="Answers"
              spec={timeSeries(d.series.map((s) => ({ x: s.bucket, y: s.runs })), "answers", { hourly })}
              rows={d.series}
              columns={columns}
            />
            <ChartPanel
              title="LLM cost"
              spec={timeSeries(d.series.map((s) => ({ x: s.bucket, y: s.cost_usd })), "cost (USD)", { money: true, hourly })}
              rows={d.series}
              columns={columns}
            />
          </div>
          <p className="text-[11px] text-neutral-400">
            Times are UTC. Time to first word is recorded for answers since this release.
          </p>
        </div>
      )}
    </SectionState>
  );
}
