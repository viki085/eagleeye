"use client";

import { ResultTable } from "@/components/data/result-table";
import { SqlBlock } from "@/components/data/sql-block";
import type { ArtifactView } from "@/lib/api";

interface ArtifactCardProps {
  artifact: ArtifactView;
  onViewAll: (artifact: ArtifactView) => void;
  onDownload: (artifact: ArtifactView) => void;
}

export function ArtifactCard({ artifact, onViewAll, onDownload }: ArtifactCardProps) {
  const shown = artifact.preview.length;
  const rows = artifact.row_count.toLocaleString("en-US");
  return (
    <section
      aria-label={`Query result: ${artifact.title}`}
      className="mt-3 flex flex-col gap-2 rounded-lg border border-neutral-200 p-3 dark:border-neutral-800"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-neutral-900 dark:text-neutral-100">
            {artifact.title}
          </h3>
          <p className="text-[11px] text-neutral-500">
            {artifact.source} · {rows} row{artifact.row_count === 1 ? "" : "s"}
            {artifact.truncated && " · showing the first rows only (row cap reached)"}
          </p>
        </div>
        <div className="flex gap-1.5 text-xs">
          {artifact.row_count > shown && (
            <button
              type="button"
              onClick={() => onViewAll(artifact)}
              className="rounded-md border border-neutral-300 px-2 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
            >
              View all {rows}
            </button>
          )}
          <button
            type="button"
            onClick={() => onDownload(artifact)}
            className="rounded-md border border-neutral-300 px-2 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            CSV
          </button>
        </div>
      </header>
      <ResultTable columns={artifact.columns.map((c) => c.name)} rows={artifact.preview} />
      {artifact.row_count > shown && (
        <p className="text-[11px] text-neutral-400">First {shown} of {rows} rows.</p>
      )}
      {artifact.assumptions && (
        <p className="text-[11px] text-neutral-500">
          <span className="font-medium">Assumptions:</span> {artifact.assumptions}
        </p>
      )}
      <SqlBlock sql={artifact.sql} />
    </section>
  );
}
