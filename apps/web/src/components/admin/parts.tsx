"use client";

import { useMemo, useState, type ReactNode } from "react";

import { VegaView } from "@/components/charts/vega-view";
import type { Loadable } from "@/hooks/use-admin-data";
import type { Spec } from "@/lib/admin-charts";

export function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <p className="text-[11px] font-medium uppercase tracking-wider text-neutral-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-neutral-500">{hint}</p>}
    </div>
  );
}

export function Panel({ title, children, actions }: {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-neutral-200 p-3 dark:border-neutral-800">
      <header className="mb-2 flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{title}</h3>
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
        <thead className="text-[11px] text-neutral-500">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={`px-2 py-1.5 font-medium ${c.numeric ? "text-right" : ""}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800">
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
export function ChartPanel<T>({ title, spec, rows, columns }: {
  title: string;
  spec: Spec;
  rows: readonly T[];
  columns: readonly Column<T>[];
}) {
  const [table, setTable] = useState(false);
  const stableSpec = useMemo(() => spec, [JSON.stringify(spec)]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Panel
      title={title}
      actions={
        <button
          type="button"
          onClick={() => setTable(!table)}
          className="rounded border border-neutral-300 px-1.5 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-100 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
        >
          {table ? "Chart" : "Table"}
        </button>
      }
    >
      {rows.length === 0 ? (
        <p className="py-6 text-center text-xs text-neutral-400">No data in this period.</p>
      ) : table ? (
        <DataTable rows={rows} columns={columns} />
      ) : (
        <VegaView spec={stableSpec} />
      )}
    </Panel>
  );
}

export function SectionState<T>({ state, children }: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === "loading") return <p className="text-sm text-neutral-400">Loading…</p>;
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
