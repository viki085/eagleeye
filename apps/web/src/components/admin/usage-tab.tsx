"use client";

import { ChartPanel, DataTable, Panel, SectionState } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { categoryBars, costByModel } from "@/lib/admin-charts";
import { count, money } from "@/lib/admin-format";
import type { AdminRange, AdminUsage, ApiClient } from "@/lib/api";

type ModelRow = AdminUsage["by_model"][number];
type UserRow = AdminUsage["top_users"][number];
type RouteRow = AdminUsage["routes"][number];
type ToolRow = AdminUsage["tools"][number];

const ROUTE_LABEL: Record<string, string> = {
  simple: "Chat (no sources)",
  rag: "Documents",
  rag_auto: "Documents (auto)",
  sql: "Database",
  supervisor: "Multi-step (tools)",
  blocked: "Blocked by safety",
  unknown: "Not recorded (older or stopped early)",
};

export function UsageTab({ api, range }: { api: ApiClient; range: AdminRange }) {
  const [state] = useAdminData(() => api.adminUsage(range), [api, range]);
  return (
    <SectionState state={state}>
      {(d) => (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
          <ChartPanel
            title="Cost per day by model"
            spec={costByModel(d.by_model)}
            rows={d.by_model}
            columns={[
              { key: "day", label: "Day", render: (r: ModelRow) => r.day },
              { key: "model", label: "Model", render: (r: ModelRow) => r.model_id },
              { key: "in", label: "Tokens in", numeric: true, render: (r: ModelRow) => count(r.tokens_in) },
              { key: "out", label: "Tokens out", numeric: true, render: (r: ModelRow) => count(r.tokens_out) },
              { key: "cost", label: "Cost", numeric: true, render: (r: ModelRow) => money(r.cost_usd, 4) },
            ]}
          />
          <ChartPanel
            title="Answers by type"
            spec={categoryBars(
              d.routes.map((r) => ({ label: ROUTE_LABEL[r.route] ?? r.route, value: r.runs })),
              "answers",
            )}
            rows={d.routes}
            columns={[
              { key: "route", label: "Type", render: (r: RouteRow) => ROUTE_LABEL[r.route] ?? r.route },
              { key: "runs", label: "Answers", numeric: true, render: (r: RouteRow) => count(r.runs) },
            ]}
          />
          <Panel title="Top users by cost">
            <DataTable
              rows={d.top_users}
              columns={[
                { key: "email", label: "User", render: (r: UserRow) => r.email },
                // usage_ledger only has answers that called a model (blocked ones cost nothing)
                { key: "runs", label: "Billed answers", numeric: true, render: (r: UserRow) => count(r.runs) },
                { key: "cost", label: "Cost", numeric: true, render: (r: UserRow) => money(r.cost_usd, 4) },
              ]}
            />
          </Panel>
          <Panel title="Tool usage">
            <DataTable
              rows={d.tools}
              columns={[
                { key: "name", label: "Step", render: (r: ToolRow) => r.name },
                { key: "calls", label: "Calls", numeric: true, render: (r: ToolRow) => count(r.calls) },
                { key: "errors", label: "Errors", numeric: true, render: (r: ToolRow) => count(r.errors) },
                { key: "ms", label: "Avg time", numeric: true, render: (r: ToolRow) => `${count(r.avg_ms)} ms` },
              ]}
            />
          </Panel>
        </div>
      )}
    </SectionState>
  );
}
