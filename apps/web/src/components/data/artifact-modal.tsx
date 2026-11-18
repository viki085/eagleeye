"use client";

import { useEffect, useState } from "react";

import { ResultTable } from "@/components/data/result-table";
import type { ApiClient, ArtifactPage, ArtifactView } from "@/lib/api";
import { useBackCloses } from "@/hooks/use-back-closes";

const PAGE_SIZE = 100;

interface ArtifactModalProps {
  api: ApiClient;
  artifact: ArtifactView | null;
  onClose: () => void;
  onDownload: (artifact: ArtifactView) => void;
}

type State = { kind: "loading" } | { kind: "ok"; page: ArtifactPage } | { kind: "error"; message: string };

export function ArtifactModal({ api, artifact, onClose, onDownload }: ArtifactModalProps) {
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => setOffset(0), [artifact]);

  useEffect(() => {
    if (artifact === null) return;
    let cancelled = false;
    setState({ kind: "loading" });
    api
      .getArtifact(artifact.artifact_id, offset, PAGE_SIZE)
      .then((page) => !cancelled && setState({ kind: "ok", page }))
      .catch((e: unknown) => {
        if (!cancelled) setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
      });
    return () => {
      cancelled = true;
    };
  }, [api, artifact, offset]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const close = useBackCloses(artifact !== null, onClose);
  if (artifact === null) return null;
  const total = state.kind === "ok" ? state.page.total : artifact.row_count;
  const end = Math.min(offset + PAGE_SIZE, total);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 md:p-4" onClick={close}>
      <section
        role="dialog"
        aria-label={artifact.title}
        onClick={(e) => e.stopPropagation()}
        className="pt-safe pb-safe flex h-dvh w-full max-w-5xl flex-col gap-3 bg-white px-3 py-3 shadow-xl md:h-auto md:max-h-[90dvh] md:rounded-xl md:border md:border-neutral-200 md:p-4 dark:bg-neutral-950 md:dark:border-neutral-800"
      >
        <header className="flex items-center justify-between gap-3">
          <h2 className="truncate text-sm font-semibold">{artifact.title}</h2>
          <div className="flex items-center gap-2 text-xs">
            <button type="button" onClick={() => onDownload(artifact)} className="rounded-md border border-neutral-300 px-2 py-1 hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800">
              CSV
            </button>
            <button type="button" onClick={close} aria-label="Close" className="flex h-9 w-9 items-center justify-center text-lg text-neutral-400 hover:text-neutral-800 md:h-auto md:w-auto md:px-1.5 md:text-base dark:hover:text-neutral-200">
              ×
            </button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1 flex-col">
          {state.kind === "loading" && <p className="text-sm text-neutral-400">Loading…</p>}
          {state.kind === "error" && <p className="text-sm text-red-600">{state.message}</p>}
          {state.kind === "ok" && (
            <ResultTable columns={state.page.columns} rows={state.page.rows} maxHeightClass="max-h-full md:max-h-[65dvh]" />
          )}
        </div>
        <footer className="flex items-center justify-between text-xs text-neutral-500">
          <span className="tabular-nums">
            Rows {total === 0 ? 0 : offset + 1}–{end} of {total.toLocaleString("en-US")}
          </span>
          <div className="flex gap-1.5">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="rounded-md border border-neutral-300 px-2 py-1 disabled:opacity-40 dark:border-neutral-700">
              Previous
            </button>
            <button type="button" disabled={end >= total} onClick={() => setOffset(offset + PAGE_SIZE)} className="rounded-md border border-neutral-300 px-2 py-1 disabled:opacity-40 dark:border-neutral-700">
              Next
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}
