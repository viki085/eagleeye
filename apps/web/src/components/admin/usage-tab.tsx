"use client";

import { ChartPanel, DataTable, Panel, SectionState } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { costByModel } from "@/lib/admin-charts";
import { count, money } from "@/lib/admin-format";
import { stepLabel } from "@/lib/admin-labels";
import type { AdminRange, AdminUsage, ApiClient } from "@/lib/api";

type ModelRow = AdminUsage["by_model"][number];
type UserRow = AdminUsage["top_users"][number];
type ToolRow = AdminUsage["tools"][number];

export function UsageTab({ api, range, refreshKey }: { api: ApiClient; range: AdminRange; refreshKey: number }) {
  const [state] = useAdminData(() => api.adminUsage(range), [api, range, refreshKey]);
  return (
    <SectionState state={state}>
      {(d) => (
        <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
          <ChartPanel
            className="xl:col-span-12"
            title="LLM cost per day by model"
            subtitle="Billed spend from the usage ledger (UTC days)"
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
          <Panel className="xl:col-span-5" title="Top users by cost" subtitle="Ten highest-spending accounts in this period">
            <DataTable
              rows={d.top_users}
              columns={[
                { key: "email", label: "User", render: (r: UserRow) => r.email },
                // usage_ledger only has requests that called a model (blocked ones cost nothing)
                { key: "runs", label: "Billed requests", numeric: true, render: (r: UserRow) => count(r.runs) },
                { key: "cost", label: "Cost", numeric: true, render: (r: UserRow) => money(r.cost_usd, 4) },
              ]}
            />
          </Panel>
          <Panel className="xl:col-span-7" title="Agent tool usage" subtitle="Tool calls made by agents, most used first">
            <DataTable
              rows={d.tools}
              columns={[
                { key: "name", label: "Tool", render: (r: ToolRow) => stepLabel("tool", r.name) },
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
