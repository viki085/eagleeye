"use client";

import { useMemo, useState, type ReactNode } from "react";

import { CARD } from "@/components/admin/kpi";
import { EChartView } from "@/components/charts/echart-view";
import type { Loadable } from "@/hooks/use-admin-data";
import type { AdminChart } from "@/lib/admin-charts";

export function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className={`${CARD} p-4`}>
      <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-neutral-500">{label}</p>
      <p className="mt-2 text-[26px] font-semibold leading-none tracking-tight text-neutral-900 dark:text-neutral-50">{value}</p>
      {hint && <p className="mt-1.5 text-[11px] text-neutral-500">{hint}</p>}
    </div>
  );
}

export function Panel({ title, subtitle, children, actions, className = "" }: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`${CARD} min-w-0 p-4 ${className}`}>
      <header className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-50">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  numeric?: boolean;
}

export function DataTable<T>({ rows, columns, empty = "Nothing here yet." }: {
  rows: readonly T[];
  columns: readonly Column<T>[];
  empty?: string;
}) {
  if (rows.length === 0) return <p className="py-2 text-xs text-neutral-400">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-[10px] uppercase tracking-[0.06em] text-neutral-500">
          <tr className="border-b border-black/[0.08] dark:border-white/10">
            {columns.map((c) => (
              <th key={c.key} className={`px-2 py-2 font-semibold ${c.numeric ? "text-right" : ""}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-black/[0.05] hover:bg-black/[0.02] dark:border-white/[0.06] dark:hover:bg-white/[0.03]">
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={`px-2 py-1.5 ${c.numeric ? "text-right tabular-nums" : ""}`}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A chart with a "Table" toggle: the data is always available without the chart. */
export function ChartPanel<T>({ title, subtitle, chart, rows, columns, className }: {
  title: string;
  subtitle?: string;
  chart: AdminChart;
  rows: readonly T[];
  columns: readonly Column<T>[];
  className?: string;
}) {
  const [table, setTable] = useState(false);
  // a new option only when the data changes (the builders run on every render)
  const option = useMemo(() => chart.option, [chart.key]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel
      title={title}
      subtitle={subtitle}
      className={className}
      actions={
        <div role="group" aria-label={`${title} view`} className="flex shrink-0 rounded-md border border-black/10 p-0.5 text-[11px] dark:border-white/10">
          {(["Chart", "Table"] as const).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={(v === "Table") === table}
              onClick={() => setTable(v === "Table")}
              className={`rounded px-2 py-0.5 ${
                (v === "Table") === table
                  ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                  : "text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      }
    >
      {rows.length === 0 ? (
        <p className="py-6 text-center text-xs text-neutral-400">No data in this period.</p>
      ) : table ? (
        <DataTable rows={rows} columns={columns} />
      ) : (
        <EChartView option={option} height={chart.height} />
      )}
    </Panel>
  );
}

export function SectionState<T>({ state, children }: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === "loading") {
    return (
      <div role="status" aria-label="Loading" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className={`${CARD} h-28 animate-pulse bg-black/[0.03] dark:bg-white/[0.04]`} />
        ))}
      </div>
    );
  }
  if (state.kind === "forbidden") return <NotAuthorised />;
  if (state.kind === "error") {
    return <p className="text-sm text-red-600 dark:text-red-400">{state.message}</p>;
  }
  return <>{children(state.data)}</>;
}

export function NotAuthorised() {
  return (
    <div className="rounded-lg border border-neutral-200 p-6 text-center dark:border-neutral-800">
      <p className="text-sm font-medium">Not authorised</p>
      <p className="mt-1 text-xs text-neutral-500">The admin console is available to administrators only.</p>
    </div>
  );
}

export function Pill({ tone, children }: { tone: "ok" | "warn" | "bad" | "muted"; children: ReactNode }) {
  const cls = {
    ok: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
    warn: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
    bad: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
    muted: "bg-neutral-200 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  }[tone];
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls}`}>{children}</span>;
}
