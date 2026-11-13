"use client";

import { ResultTable } from "@/components/data/result-table";
import { SqlBlock } from "@/components/data/sql-block";
import type { ArtifactView } from "@/lib/api";

interface ArtifactCardProps {
  artifact: ArtifactView;
  onViewAll: (artifact: ArtifactView) => void;
  onDownload: (artifact: ArtifactView) => void;
}

const CODE_LABEL = { sql: "SQL", duckdb: "DuckDB SQL", python: "Python" } as const;

const BUTTON =
  "rounded-md border border-neutral-300 px-2 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800";

/** Collapsed by default: the answer leads; the table, CSV and SQL are one click away. */
export function ArtifactCard({ artifact, onViewAll, onDownload }: ArtifactCardProps) {
  const shown = artifact.preview.length;
  const rows = artifact.row_count.toLocaleString("en-US");
  const rowLabel = `${rows} row${artifact.row_count === 1 ? "" : "s"}`;
  return (
    <details
      aria-label={`Query result: ${artifact.title}`}
      className="group mt-3 rounded-lg border border-neutral-200 dark:border-neutral-800"
    >
      <summary className="flex cursor-pointer list-none items-baseline gap-2 px-3 py-2 text-xs [&::-webkit-details-marker]:hidden">
        <span className="text-neutral-400 transition-transform group-open:rotate-90">▸</span>
        <span className="min-w-0 truncate font-medium text-neutral-800 dark:text-neutral-200">
          {artifact.title}
        </span>
        <span className="shrink-0 text-neutral-500">
          {artifact.source} · {rowLabel}
          {artifact.truncated && " (capped)"} · table &amp; SQL
        </span>
      </summary>
      <div className="flex flex-col gap-2 border-t border-neutral-200 p-3 dark:border-neutral-800">
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
          <p className="text-[11px] text-neutral-500">
            {artifact.row_count > shown ? `First ${shown} of ${rows} rows` : rowLabel}
            {artifact.truncated && " · row cap reached, showing the first rows only"}
          </p>
          <div className="flex gap-1.5">
            {artifact.row_count > shown && (
              <button type="button" onClick={() => onViewAll(artifact)} className={BUTTON}>
                View all {rows}
              </button>
            )}
            <button type="button" onClick={() => onDownload(artifact)} className={BUTTON}>
              CSV
            </button>
          </div>
        </div>
        <ResultTable columns={artifact.columns.map((c) => c.name)} rows={artifact.preview} />
        {artifact.assumptions && (
          <p className="text-[11px] text-neutral-500">
            <span className="font-medium">Assumptions:</span> {artifact.assumptions}
          </p>
        )}
        <SqlBlock sql={artifact.sql} label={CODE_LABEL[artifact.mode ?? "sql"]} />
      </div>
    </details>
  );
}
