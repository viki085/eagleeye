"use client";

import { ChartPanel } from "@/components/admin/parts";
import { StepLatencyChange, StepLatencyTrend } from "@/components/admin/step-latency";
import { donut, outcomeBars, rankedBars } from "@/lib/admin-charts";
import { bucketLabel, count, money, ratePct } from "@/lib/admin-format";
import { routeLabel, stepLabel } from "@/lib/admin-labels";
import type { AdminModelCost, AdminOverview, AdminSeriesPoint, AdminSlowStep } from "@/lib/api";

type RouteRow = AdminOverview["routes"][number];

function secondsLabel(ms: number): string {
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function OverviewCharts({ d, hourly }: { d: AdminOverview; hourly: boolean }) {
  const totalCost = d.cost_by_model.reduce((sum, m) => sum + m.cost_usd, 0);
  const totalRequests = d.routes.reduce((sum, r) => sum + r.requests, 0);
  return (
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
      <ChartPanel
        className="xl:col-span-8"
        title="Request volume and outcomes"
        subtitle={hourly ? "Requests per hour by final status (UTC)" : "Requests per day by final status (UTC)"}
        chart={outcomeBars(
          d.series.map((s) => ({
            bucket: s.bucket,
            succeeded: s.succeeded,
            failed: s.failed,
            other: Math.max(0, s.requests - s.succeeded - s.failed),
          })),
          hourly,
        )}
        rows={d.series.filter((s) => s.requests > 0)}
        columns={[
          { key: "b", label: hourly ? "Hour (UTC)" : "Day", render: (r: AdminSeriesPoint) => bucketLabel(r.bucket, hourly) },
          { key: "req", label: "Requests", numeric: true, render: (r: AdminSeriesPoint) => count(r.requests) },
          { key: "ok", label: "Succeeded", numeric: true, render: (r: AdminSeriesPoint) => count(r.succeeded) },
          { key: "fail", label: "Failed", numeric: true, render: (r: AdminSeriesPoint) => count(r.failed) },
          { key: "users", label: "Users", numeric: true, render: (r: AdminSeriesPoint) => count(r.users) },
          { key: "cost", label: "Cost", numeric: true, render: (r: AdminSeriesPoint) => money(r.cost_usd, 4) },
        ]}
      />
      <ChartPanel
        className="xl:col-span-4"
        title="LLM cost by model"
        subtitle="Share of spend per model in this period"
        chart={donut(
          d.cost_by_model.map((m) => ({ label: m.model_id, value: m.cost_usd })),
          { value: money(totalCost), caption: "total spend" },
          { money: true },
        )}
        rows={d.cost_by_model}
        columns={[
          { key: "m", label: "Model", render: (r: AdminModelCost) => r.model_id },
          { key: "calls", label: "Calls", numeric: true, render: (r: AdminModelCost) => count(r.calls) },
          { key: "tok", label: "Tokens", numeric: true, render: (r: AdminModelCost) => count(r.tokens) },
          { key: "cost", label: "Cost", numeric: true, render: (r: AdminModelCost) => money(r.cost_usd, 4) },
          { key: "share", label: "Share", numeric: true, render: (r: AdminModelCost) => ratePct(totalCost ? r.cost_usd / totalCost : null) },
        ]}
      />
      <StepLatencyTrend d={d} hourly={hourly} />
      <StepLatencyChange d={d} />
      <ChartPanel
        className="xl:col-span-5"
        title="Request routing distribution"
        subtitle="Execution path the orchestrator selected for each request"
        chart={rankedBars(
          d.routes.map((r) => ({
            label: routeLabel(r.route),
            value: r.requests,
            tooltip: { Share: ratePct(totalRequests ? r.requests / totalRequests : null) },
          })),
          { title: "requests", format: ",d" },
        )}
        rows={d.routes}
        columns={[
          { key: "r", label: "Route", render: (r: RouteRow) => routeLabel(r.route) },
          { key: "n", label: "Requests", numeric: true, render: (r: RouteRow) => count(r.requests) },
          { key: "s", label: "Share", numeric: true, render: (r: RouteRow) => ratePct(totalRequests ? r.requests / totalRequests : null) },
        ]}
      />
      <ChartPanel
        className="xl:col-span-7"
        title="Slowest pipeline steps"
        subtitle="Mean duration per execution, highest first · agent steps include their sub-steps"
        chart={rankedBars(
          d.slow_steps.map((s) => ({
            label: stepLabel(s.kind, s.name),
            value: Math.round(s.avg_ms) / 1000,
            tooltip: {
              Executions: count(s.executions),
              "p95": secondsLabel(s.p95_ms),
              "Error rate": ratePct(s.executions ? s.errors / s.executions : null),
            },
          })),
          { title: "avg seconds", format: ".2f" },
        )}
        rows={d.slow_steps}
        columns={[
          { key: "s", label: "Step", render: (r: AdminSlowStep) => stepLabel(r.kind, r.name) },
          { key: "n", label: "Executions", numeric: true, render: (r: AdminSlowStep) => count(r.executions) },
          { key: "avg", label: "Avg", numeric: true, render: (r: AdminSlowStep) => secondsLabel(r.avg_ms) },
          { key: "p95", label: "p95", numeric: true, render: (r: AdminSlowStep) => secondsLabel(r.p95_ms) },
          { key: "err", label: "Errors", numeric: true, render: (r: AdminSlowStep) => count(r.errors) },
        ]}
      />
    </div>
  );
}
