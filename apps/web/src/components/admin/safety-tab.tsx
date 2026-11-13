"use client";

import { ChartPanel, DataTable, Panel, Pill, SectionState, StatTile } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { categoryBars } from "@/lib/admin-charts";
import { count, pct, when } from "@/lib/admin-format";
import type { AdminRange, AdminSafety, ApiClient } from "@/lib/api";

type EventRow = AdminSafety["events"][number];
type SqlRow = AdminSafety["sql_rejections"][number];
type SandboxRow = AdminSafety["sandbox"][number];
type FailedRow = AdminSafety["failed_runs"][number];
type ActionRow = AdminSafety["admin_actions"][number];

const ACTION_LABEL: Record<string, string> = {
  switch_off: "Turned off",
  switch_on: "Turned on",
  clear_stuck_runs: "Cleared stuck answers",
  enterprise_doc_added: "Added enterprise document",
  enterprise_doc_deleted: "Deleted enterprise document",
};

function actionText(a: ActionRow): string {
  const label = ACTION_LABEL[a.category] ?? a.category;
  const detail = a.detail as { switch?: string; cleared?: number; title?: string };
  if (detail.switch) return `${label}: ${detail.switch}`;
  if (detail.title) return `${label}: ${detail.title}`;
  if (detail.cleared !== undefined) return `${label} (${detail.cleared})`;
  return label;
}

export function SafetyTab({ api, range }: { api: ApiClient; range: AdminRange }) {
  const [state] = useAdminData(() => api.adminSafety(range), [api, range]);
  return (
    <SectionState state={state}>
      {(d) => {
        const blocked = d.events.reduce((n, e) => n + e.events, 0);
        const rejected = d.sql_rejections.reduce((n, r) => n + r.queries, 0);
        const sandboxFailed = d.sandbox.filter((s) => s.status !== "ok").reduce((n, s) => n + s.runs, 0);
        const sandboxAll = d.sandbox.reduce((n, s) => n + s.runs, 0);
        return (
          <div className="flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <StatTile label="Safety events" value={count(blocked)} hint="blocked or flagged requests" />
              <StatTile label="SQL refused or failed" value={count(rejected)} hint={`of ${count(d.sql_queries)} queries`} />
              <StatTile label="Sandbox failures" value={pct(sandboxFailed, sandboxAll)} hint={`${count(sandboxFailed)} of ${count(sandboxAll)} runs`} />
              <StatTile
                label="Unverified figures"
                value={pct(d.unverified_figures.unverified, d.unverified_figures.finished)}
                hint={`${count(d.unverified_figures.unverified)} answers flagged`}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <ChartPanel
                title="Safety events by category"
                spec={categoryBars(d.events.map((e) => ({ label: `${e.category} (${e.kind})`, value: e.events })), "events")}
                rows={d.events}
                columns={[
                  { key: "cat", label: "Category", render: (r: EventRow) => r.category },
                  { key: "kind", label: "Where", render: (r: EventRow) => r.kind },
                  { key: "n", label: "Events", numeric: true, render: (r: EventRow) => count(r.events) },
                ]}
              />
              <ChartPanel
                title="SQL refusals and errors"
                spec={categoryBars(d.sql_rejections.map((r) => ({ label: r.reason, value: r.queries })), "queries")}
                rows={d.sql_rejections}
                columns={[
                  { key: "reason", label: "Reason", render: (r: SqlRow) => r.reason },
                  { key: "n", label: "Queries", numeric: true, render: (r: SqlRow) => count(r.queries) },
                ]}
              />
              <Panel title="Sandbox runs">
                <DataTable
                  rows={d.sandbox}
                  columns={[
                    { key: "mode", label: "Mode", render: (r: SandboxRow) => (r.mode === "sql" ? "DuckDB SQL" : "Python") },
                    { key: "status", label: "Result", render: (r: SandboxRow) => <Pill tone={r.status === "ok" ? "ok" : "bad"}>{r.status}</Pill> },
                    { key: "n", label: "Runs", numeric: true, render: (r: SandboxRow) => count(r.runs) },
                    { key: "ms", label: "Avg time", numeric: true, render: (r: SandboxRow) => `${count(r.avg_ms)} ms` },
                  ]}
                />
              </Panel>
              <Panel title="Recent failed answers">
                <DataTable
                  rows={d.failed_runs}
                  empty="No failed answers in this period."
                  columns={[
                    { key: "when", label: "When", render: (r: FailedRow) => when(r.created_at) },
                    { key: "user", label: "User", render: (r: FailedRow) => r.email },
                    { key: "code", label: "Error", render: (r: FailedRow) => r.error_code ?? r.status },
                    { key: "route", label: "Type", render: (r: FailedRow) => r.route ?? "—" },
                  ]}
                />
              </Panel>
            </div>
            <Panel title="Admin actions">
              <DataTable
                rows={d.admin_actions}
                empty="No admin actions yet."
                columns={[
                  { key: "when", label: "When", render: (r: ActionRow) => when(r.created_at) },
                  { key: "who", label: "Admin", render: (r: ActionRow) => r.email ?? "—" },
                  { key: "what", label: "Action", render: (r: ActionRow) => actionText(r) },
                ]}
              />
            </Panel>
          </div>
        );
      }}
    </SectionState>
  );
}
