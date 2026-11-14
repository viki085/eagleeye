"use client";

import { DeltaBadge, KpiCard, StatusCard, type Health } from "@/components/admin/kpi";
import { OverviewCharts } from "@/components/admin/overview-charts";
import { SectionState } from "@/components/admin/parts";
import { UsageGlance } from "@/components/admin/usage-glance";
import { useAdminData } from "@/hooks/use-admin-data";
import { compare, rateDelta, type Better } from "@/lib/admin-kpi";
import { count, money, ratePct, seconds, when } from "@/lib/admin-format";
import type { AdminOverview, AdminRange, ApiClient } from "@/lib/api";

const VERSUS: Record<AdminRange, string> = {
  "24h": "vs prev. 24 h",
  "7d": "vs prev. 7 days",
  "14d": "vs prev. 14 days",
  "30d": "vs prev. 30 days",
};

function Change({ cur, prev, better, range }: { cur: number | null; prev: number | null; better: Better; range: AdminRange }) {
  const c = compare(cur, prev, better);
  if (!c) return <span className="text-[11px] text-neutral-500">No data for previous period</span>;
  const text = `${c.pct > 0 ? "+" : ""}${c.pct}%`;
  return <DeltaBadge text={text} direction={c.direction} tone={c.tone} versus={VERSUS[range]} />;
}

function RateChange({ cur, prev, better, range }: { cur: number | null; prev: number | null; better: Better; range: AdminRange }) {
  const d = rateDelta(cur, prev, better);
  if (!d) return <span className="text-[11px] text-neutral-500">No data for previous period</span>;
  const text = `${d.points > 0 ? "+" : ""}${d.points} pts`;
  return <DeltaBadge text={text} direction={d.direction} tone={d.tone} versus={VERSUS[range]} />;
}

function KpiRow({ d, range }: { d: AdminOverview; range: AdminRange }) {
  const { current: cur, previous: prev, series } = d;
  const share = d.total_users ? Math.round((100 * cur.active_users) / d.total_users) : 0;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
      <KpiCard
        label="Active users" icon="users" value={count(cur.active_users)}
        delta={<Change cur={cur.active_users} prev={prev.active_users} better="up" range={range} />}
        hint={`${share}% of ${count(d.total_users)} accounts · ${cur.active_users ? (cur.requests / cur.active_users).toFixed(1) : "0"} answers each`}
        trend={series.map((s) => s.users)}
      />
      <KpiCard
        label="Success rate" icon="check" value={ratePct(cur.success_rate)}
        delta={<RateChange cur={cur.success_rate} prev={prev.success_rate} better="up" range={range} />}
        hint={`${count(cur.succeeded)} of ${count(cur.requests)} completed`}
        trend={series.map((s) => (s.requests ? s.succeeded / s.requests : null))}
      />
      <KpiCard
        label="Failure rate" icon="alert" value={ratePct(cur.failure_rate)}
        delta={<RateChange cur={cur.failure_rate} prev={prev.failure_rate} better="down" range={range} />}
        hint={`${count(cur.failed)} failed · ${count(cur.cancelled)} cancelled · ${count(cur.degraded)} on fallback model`}
        trend={series.map((s) => s.failed)}
      />
      <KpiCard
        label="LLM cost" icon="coin" value={money(cur.cost_usd)}
        delta={<Change cur={cur.cost_usd} prev={prev.cost_usd} better="down" range={range} />}
        hint={cur.cost_per_request_usd === null ? undefined : `${money(cur.cost_per_request_usd, 4)} per request`}
        trend={series.map((s) => s.cost_usd)}
      />
      <KpiCard
        label="Avg response time" icon="clock" value={seconds(cur.avg_duration_s)}
        delta={<Change cur={cur.avg_duration_s} prev={prev.avg_duration_s} better="down" range={range} />}
        hint={`p95 ${seconds(cur.p95_duration_s)} · first token ${seconds(cur.avg_ttft_s)}`}
        trend={series.map((s) => s.avg_duration_s)}
      />
    </div>
  );
}

const DB_HEALTH: Record<AdminOverview["live"]["databases"]["status"], [Health, string]> = {
  healthy: ["ok", "Healthy"],
  degraded: ["warn", "Degraded"],
  down: ["bad", "Down"],
};

function StatusRow({ d, range }: { d: AdminOverview; range: AdminRange }) {
  const { databases, agents } = d.live;
  const [dbHealth, dbText] = DB_HEALTH[databases.status];
  const k = d.knowledge;
  const safety = d.current.safety_events;
  const perK = d.current.requests ? ((1000 * safety) / d.current.requests).toFixed(1) : "0";
  const safetyChange = compare(safety, d.previous.safety_events, "down");
  const agentHealth: Health = agents.stuck > 0 ? "warn" : agents.active > 0 ? "ok" : "idle";
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 2xl:grid-cols-4">
      <StatusCard
        label="Database health" icon="database"
        value={databases.primary_latency_ms === null ? "—" : `${databases.primary_latency_ms} ms`}
        status={dbHealth} statusText={`${dbText} · ${databases.up}/${databases.total} up`}
        rows={databases.items.map((i) => ({
          label: i.name,
          value: i.status === "up" ? `${i.latency_ms ?? "—"} ms` : "down",
          health: i.status === "up" ? "ok" : "bad",
        }))}
      />
      <StatusCard
        label="Active agents" icon="agent" value={count(agents.active)}
        status={agentHealth}
        statusText={agents.stuck > 0 ? `${count(agents.stuck)} stalled` : agents.active > 0 ? "Processing" : "Idle"}
        rows={[
          { label: "Requests executing or queued now", value: count(agents.active) },
          { label: "Stalled (no worker heartbeat)", value: count(agents.stuck), health: agents.stuck ? "warn" : "ok" },
        ]}
      />
      <StatusCard
        label="Safety events" icon="safety" value={count(safety)}
        status={safety === 0 ? "ok" : "warn"}
        statusText={safety === 0 ? "None in period" : "Review in Quality & safety"}
        rows={[
          { label: "Per 1,000 requests", value: perK },
          {
            label: VERSUS[range].replace("vs ", "Change vs "),
            value: safetyChange ? `${safetyChange.pct > 0 ? "+" : ""}${safetyChange.pct}%` : "—",
          },
        ]}
      />
      <StatusCard
        label="Enterprise knowledge" icon="book" value={`${count(k.ready)} docs`}
        status={k.failed > 0 ? "bad" : k.indexing > 0 ? "warn" : "ok"}
        statusText={k.failed > 0 ? `${count(k.failed)} failed` : k.indexing > 0 ? `Indexing ${count(k.indexing)}` : "All indexed"}
        rows={[
          { label: "Searchable chunks", value: count(k.chunks) },
          { label: "Indexing / failed", value: `${count(k.indexing)} / ${count(k.failed)}` },
        ]}
      />
    </div>
  );
}

export function OverviewTab({ api, range, refreshKey }: { api: ApiClient; range: AdminRange; refreshKey: number }) {
  const [state, reload] = useAdminData(() => api.adminOverview(range), [api, range, refreshKey]);
  return (
    <SectionState state={state}>
      {(d) => (
        <div className="flex flex-col gap-4">
          <UsageGlance d={d} hourly={range === "24h"} api={api} onBudgetChanged={reload} />
          <KpiRow d={d} range={range} />
          <StatusRow d={d} range={range} />
          <OverviewCharts d={d} hourly={range === "24h"} />
          <p className="text-[11px] text-neutral-500">
            Figures as of {when(d.generated_at)} · refreshed at most once a minute · times in UTC ·
            cost from the billing ledger · first-token time recorded since this release
          </p>
        </div>
      )}
    </SectionState>
  );
}
