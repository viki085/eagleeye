"use client";

import { EmptyNote } from "@/components/documents/panel-section";
import type { DatasetStatus, DatasetSummary } from "@/lib/api";

interface DatasetListProps {
  datasets: readonly DatasetSummary[];
  onProfile: (dataset: DatasetSummary) => void;
  onDelete: (dataset: DatasetSummary) => void;
}

const STATUS_LABEL: Record<DatasetStatus, string> = {
  UPLOADED: "Queued",
  PROFILING: "Profiling",
  READY: "Ready",
  FAILED: "Failed",
};

const STATUS_CLASS: Record<DatasetStatus, string> = {
  UPLOADED: "bg-neutral-200 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  PROFILING: "bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300",
  READY: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  FAILED: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
};

/** Uploaded CSV/Excel files the assistant can analyse (each workbook sheet is its own row). */
export function DatasetList({ datasets, onProfile, onDelete }: DatasetListProps) {
  if (datasets.length === 0) {
    return <EmptyNote>No data files yet. Upload a CSV or Excel file to analyse it.</EmptyNote>;
  }
  return (
    <ul className="flex flex-col">
      {datasets.map((d) => (
        <li
          key={d.id}
          className="group flex items-start justify-between gap-2 rounded-md px-2 py-1.5 hover:bg-neutral-100 dark:hover:bg-neutral-800/60"
        >
          <div className="min-w-0">
            <p className="truncate text-sm text-neutral-800 dark:text-neutral-200" title={d.filename}>
              {d.title}
            </p>
            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px]">
              <span className={`rounded px-1.5 py-0.5 font-medium ${STATUS_CLASS[d.status]}`}>
                {STATUS_LABEL[d.status]}
              </span>
              {d.status === "READY" && (
                <span className="tabular-nums text-neutral-500">
                  {d.row_count.toLocaleString("en-US")} rows · {d.column_count} cols
                </span>
              )}
            </div>
            {d.status === "FAILED" && d.error && (
              <p className="mt-0.5 text-[11px] text-red-600 dark:text-red-400">{d.error}</p>
            )}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {d.status === "READY" && (
              <button
                type="button"
                onClick={() => onProfile(d)}
                className="rounded border border-neutral-300 px-1.5 py-0.5 text-[11px] text-neutral-600 hover:bg-white dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-900"
              >
                Profile
              </button>
            )}
            <button
              type="button"
              onClick={() => onDelete(d)}
              aria-label={`Delete ${d.title}`}
              className="rounded px-1 text-neutral-400 opacity-0 hover:text-red-600 focus:opacity-100 group-hover:opacity-100"
            >
              ×
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
