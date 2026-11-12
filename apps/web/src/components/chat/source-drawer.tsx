"use client";

import { useEffect, useState } from "react";

import type { ApiClient, ChunkDetail, Citation } from "@/lib/api";

interface SourceDrawerProps {
  api: ApiClient;
  citation: Citation | null;
  onClose: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; chunk: ChunkDetail }
  | { kind: "error"; message: string };

export function SourceDrawer({ api, citation, onClose }: SourceDrawerProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  useEffect(() => {
    if (citation === null) return;
    let cancelled = false;
    setState({ kind: "loading" });
    api
      .getChunk(citation.document_id, citation.chunk_id)
      .then((chunk) => !cancelled && setState({ kind: "loaded", chunk }))
      .catch((e: unknown) => {
        if (!cancelled) {
          setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, citation]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (citation === null) return null;
  const path = [citation.title, ...citation.heading_path].join(" › ");

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/20" onClick={onClose}>
      <section
        role="dialog"
        aria-label={`Source ${citation.n}`}
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full max-w-lg flex-col border-l border-neutral-200 bg-white shadow-xl dark:border-neutral-800 dark:bg-neutral-950"
      >
        <header className="flex items-start justify-between gap-3 border-b border-neutral-200 p-4 dark:border-neutral-800">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-wide text-neutral-400">
              Source [{citation.n}] · {citation.scope}
              {citation.page !== null && ` · page ${citation.page}`}
            </p>
            <h2 className="mt-1 text-sm font-medium">{path}</h2>
          </div>
          <button onClick={onClose} aria-label="Close source" className="text-neutral-400 hover:text-neutral-700">
            ×
          </button>
        </header>
        <div className="flex-1 overflow-y-auto p-4 text-sm leading-relaxed">
          {state.kind === "loading" && <p className="text-neutral-400">Loading…</p>}
          {state.kind === "error" && <p className="text-red-600">{state.message}</p>}
          {state.kind === "loaded" && (
            <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-200">{state.chunk.content}</p>
          )}
        </div>
      </section>
    </div>
  );
}
