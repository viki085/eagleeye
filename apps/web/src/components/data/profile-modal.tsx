"use client";

import { useEffect, useState } from "react";

import { ResultTable } from "@/components/data/result-table";
import type { ApiClient, DatasetDetail, DatasetSummary, ProfileColumn } from "@/lib/api";
import { useBackCloses } from "@/hooks/use-back-closes";

interface ProfileModalProps {
  api: ApiClient;
  dataset: DatasetSummary | null;
  onClose: () => void;
}

type State = { kind: "loading" } | { kind: "ok"; detail: DatasetDetail } | { kind: "error"; message: string };

const FLAG_LABEL: Record<string, string> = {
  pii: "personal data",
  id_like: "ID-like",
  constant: "constant",
  mostly_null: "mostly empty",
  mixed_types: "mixed types",
};

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") {
    return Number.isInteger(v) ? v.toLocaleString("en-US") : v.toLocaleString("en-US", { maximumFractionDigits: 3 });
  }
  return String(v).slice(0, 19);
}

function stats(c: ProfileColumn): string {
  if (c.kind === "numeric") return `${fmt(c.min)} – ${fmt(c.max)} · mean ${fmt(c.mean)} · median ${fmt(c.median)}`;
  if (c.kind === "temporal") return `${fmt(c.min)} → ${fmt(c.max)}`;
  if (c.top?.length) return c.top.map((t) => `${fmt(t.value)} (${t.count})`).join(", ");
  return "";
}

function ColumnsTable({ columns }: { columns: ProfileColumn[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-neutral-200 dark:border-neutral-800">
      <table className="w-full text-left text-xs">
        <thead className="bg-neutral-50 text-[11px] text-neutral-500 dark:bg-neutral-900">
          <tr>
            <th className="px-2 py-1.5 font-medium">Column</th>
            <th className="px-2 py-1.5 font-medium">Type</th>
            <th className="px-2 py-1.5 text-right font-medium">Empty</th>
            <th className="px-2 py-1.5 text-right font-medium">Distinct</th>
            <th className="px-2 py-1.5 font-medium">Values</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((c) => (
            <tr key={c.name} className="border-t border-neutral-100 align-top dark:border-neutral-800">
              <td className="px-2 py-1.5">
                <code className="text-[11px]">{c.name}</code>
                {c.original !== c.name && <div className="text-[10px] text-neutral-400">{c.original}</div>}
                {c.flags.length > 0 && (
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {c.flags.map((f) => (
                      <span key={f} className="rounded bg-neutral-100 px-1 text-[10px] text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                        {FLAG_LABEL[f] ?? f}
                      </span>
                    ))}
                  </div>
                )}
              </td>
              <td className="px-2 py-1.5 text-neutral-500">{c.type.toLowerCase()}</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmt(c.null_pct)}%</td>
              <td className="px-2 py-1.5 text-right tabular-nums">{fmt(c.distinct)}</td>
              <td className="px-2 py-1.5 text-neutral-600 dark:text-neutral-300">{stats(c)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The automatic EDA profile of one data file. */
export function ProfileModal({ api, dataset, onClose }: ProfileModalProps) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (dataset === null) return;
    let cancelled = false;
    setState({ kind: "loading" });
    api
      .getDataset(dataset.id)
      .then((detail) => !cancelled && setState({ kind: "ok", detail }))
      .catch((e: unknown) => {
        if (!cancelled) setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
      });
    return () => {
      cancelled = true;
    };
  }, [api, dataset]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const close = useBackCloses(dataset !== null, onClose);
  if (dataset === null) return null;
  const profile = state.kind === "ok" ? state.detail.profile : null;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 md:p-4" onClick={close}>
      <section
        role="dialog"
        aria-label={`Profile of ${dataset.title}`}
        onClick={(e) => e.stopPropagation()}
        className="pt-safe pb-safe flex h-dvh w-full max-w-5xl flex-col gap-3 overflow-y-auto bg-white px-3 py-3 shadow-xl md:h-auto md:max-h-[90dvh] md:rounded-xl md:border md:border-neutral-200 md:p-4 dark:bg-neutral-950 md:dark:border-neutral-800"
      >
        <header className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold">{dataset.title}</h2>
            {profile && (
              <p className="text-xs tabular-nums text-neutral-500">
                {fmt(profile.row_count)} rows · {fmt(profile.column_count)} columns ·{" "}
                {fmt(profile.duplicate_rows)} duplicated rows
              </p>
            )}
          </div>
          <button type="button" onClick={close} aria-label="Close" className="-m-2 flex h-10 w-10 shrink-0 items-center justify-center text-lg text-neutral-400 hover:text-neutral-800 md:m-0 md:h-auto md:w-auto md:px-1.5 md:text-base dark:hover:text-neutral-200">
            ×
          </button>
        </header>
        {state.kind === "loading" && <p className="text-sm text-neutral-400">Loading…</p>}
        {state.kind === "error" && <p className="text-sm text-red-600">{state.message}</p>}
        {state.kind === "ok" && (
          <>
            {state.detail.summary && (
              <p className="text-sm text-neutral-700 dark:text-neutral-300">{state.detail.summary}</p>
            )}
            {(profile?.warnings?.length ?? 0) > 0 && (
              <ul className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300">
                {profile?.warnings?.map((w) => <li key={w}>{w}</li>)}
              </ul>
            )}
            {profile?.columns && <ColumnsTable columns={profile.columns} />}
            {(profile?.correlations?.length ?? 0) > 0 && (
              <div className="text-xs">
                <h3 className="mb-1 font-medium text-neutral-700 dark:text-neutral-300">Strongest correlations</h3>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 tabular-nums text-neutral-600 dark:text-neutral-400">
                  {profile?.correlations?.map((c) => (
                    <li key={`${c.a}-${c.b}`}>
                      <code>{c.a}</code> ~ <code>{c.b}</code>: r = {c.r.toFixed(2)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {profile?.sample && profile.sample.rows.length > 0 && (
              <div className="text-xs">
                <h3 className="mb-1 font-medium text-neutral-700 dark:text-neutral-300">
                  Sample rows <span className="font-normal text-neutral-400">(*** = personal data, hidden from the assistant)</span>
                </h3>
                <ResultTable columns={profile.sample.columns} rows={profile.sample.rows} maxHeightClass="max-h-72" />
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
