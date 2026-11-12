"use client";

import type { DocumentStatus, DocumentSummary } from "@/lib/api";

const STAGE_LABEL: Record<DocumentStatus, string> = {
  UPLOADING: "Uploading",
  SCANNING: "Scanning",
  PARSING: "Parsing",
  CHUNKING: "Chunking",
  EMBEDDING: "Embedding",
  READY: "Ready",
  FAILED: "Failed",
};

function statusClass(status: DocumentStatus): string {
  if (status === "READY") return "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300";
  if (status === "FAILED") return "bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300";
  return "animate-pulse bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300";
}

interface DocumentRowProps {
  doc: DocumentSummary;
  selected: boolean;
  canDelete: boolean;
  onToggle: () => void;
  onDelete: () => void;
}

export function DocumentRow({ doc, selected, canDelete, onToggle, onDelete }: DocumentRowProps) {
  const ready = doc.status === "READY";
  return (
    <li className="group rounded-lg px-2 py-2 hover:bg-neutral-100 dark:hover:bg-neutral-800/60">
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={selected}
          disabled={!ready}
          onChange={onToggle}
          aria-label={`Use ${doc.title} in this question`}
          className="mt-0.5 accent-blue-600 disabled:opacity-30"
        />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm" title={doc.filename}>
            {doc.title}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
            <span className={`rounded px-1.5 py-0.5 font-medium ${statusClass(doc.status)}`}>
              {STAGE_LABEL[doc.status]}
            </span>
            <span className="rounded bg-neutral-200 px-1.5 py-0.5 capitalize text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400">
              {doc.scope}
            </span>
            {ready && doc.chunk_count !== null && (
              <span className="text-neutral-400">
                {doc.page_count ? `${doc.page_count} p · ` : ""}
                {doc.chunk_count} chunks
              </span>
            )}
          </div>
          {doc.status === "FAILED" && doc.error && (
            <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">{doc.error}</p>
          )}
        </div>
        {canDelete && (
          <button
            onClick={onDelete}
            aria-label={`Delete ${doc.title}`}
            className="rounded px-1 text-neutral-400 opacity-0 hover:text-red-500 focus:opacity-100 group-hover:opacity-100"
          >
            ×
          </button>
        )}
      </div>
    </li>
  );
}
