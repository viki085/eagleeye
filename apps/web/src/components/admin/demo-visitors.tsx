"use client";

import { DataTable, Panel, Pill, SectionState, type Column } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { count, money, when } from "@/lib/admin-format";
import type { AdminDemoVisit, ApiClient } from "@/lib/api";

const STATUS: Record<AdminDemoVisit["status"], [string, "ok" | "warn" | "muted"]> = {
  active: ["Active", "ok"],
  used_up: ["Used up", "warn"],
  expired: ["Expired", "muted"],
  tester: ["Tester", "ok"], // an exempt network (the owner's own testing): no limits
};

function minutes(seconds: number): string {
  return `${Math.min(Math.round(seconds / 60), 999)}`;
}

function columns(limitS: number, budget: number): Column<AdminDemoVisit>[] {
  return [
    {
      key: "network",
      label: "Visitor",
      render: (v) => (
        <span className="flex items-center gap-1.5">
          {v.online && <span aria-label="online" title="Online now" className="h-2 w-2 shrink-0 rounded-full bg-[#0ca30c]" />}
          <span className="font-mono text-[11px]">{v.network}</span>
        </span>
      ),
    },
    { key: "started", label: "Started", render: (v) => when(v.started_at) },
    { key: "active", label: "Last active", render: (v) => (v.online ? "online now" : when(v.last_active_at)) },
    { key: "time", label: "Time used", render: (v) => `${minutes(v.seconds_used)} / ${minutes(limitS)} min` },
    { key: "spend", label: "AI spend", render: (v) => `${money(v.spend_usd, 4)} / ${money(budget, 2)}` },
    { key: "questions", label: "Questions", render: (v) => count(v.questions) },
    { key: "notebook", label: "Notebook", render: (v) => (v.notebook_used ? "used" : "—") },
    {
      key: "status",
      label: "Status",
      render: (v) => {
        const [text, tone] = STATUS[v.status];
        return <Pill tone={tone}>{text}</Pill>;
      },
    },
  ];
}

/** The last 7 days' demo visits (one per visitor network per 24 h). No chat content. */
export function DemoVisitorsPanel({ api, refreshKey }: { api: ApiClient; refreshKey: number }) {
  const [state] = useAdminData(() => api.adminDemoVisitors(), [api, refreshKey]);
  return (
    <SectionState state={state}>
      {(d) => (
        <Panel
          title={`Demo visitors (${count(d.items.length)})`}
          subtitle={`Today's demo AI spend: ${money(d.today_spend_usd, 4)} of the ${money(d.limits.daily_budget_usd, 2)} daily cap. Networks are masked; chat content is never shown.`}
        >
          <DataTable
            rows={d.items}
            columns={columns(d.limits.visit_seconds, d.limits.visit_budget_usd)}
            empty="No demo visits in the last 7 days."
          />
        </Panel>
      )}
    </SectionState>
  );
}
