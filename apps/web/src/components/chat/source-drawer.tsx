"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { ApiClient, ChunkDetail, Citation } from "@/lib/api";
import { isSourceGone } from "@/lib/citation";

interface SourceDrawerProps {
  api: ApiClient;
  citation: Citation | null;
  onClose: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "loaded"; chunk: ChunkDetail }
  | { kind: "saved" } // passage gone (re-indexed or deleted): show the snippet saved with the answer
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
        if (cancelled) return;
        if (isSourceGone(e)) setState({ kind: "saved" });
        else setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
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
          {state.kind === "saved" && (
            <>
              <p className="mb-3 rounded-md bg-neutral-100 px-3 py-2 text-xs text-neutral-600 dark:bg-neutral-900 dark:text-neutral-400">
                This document has been updated or re-indexed since the answer was written, so the
                full passage is no longer available. Showing the excerpt saved with the answer.
              </p>
              <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-200">{citation.snippet}</p>
            </>
          )}
          {state.kind === "loaded" && state.chunk.element_type === "table" && (
            // a table chunk is Markdown (from the PDF parser): shown as a table; raw HTML is not rendered
            <div className="overflow-x-auto text-xs text-neutral-800 dark:text-neutral-200 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-neutral-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-neutral-200 [&_th]:bg-neutral-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left dark:[&_td]:border-neutral-800 dark:[&_th]:border-neutral-800 dark:[&_th]:bg-neutral-900">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.chunk.content}</ReactMarkdown>
            </div>
          )}
          {state.kind === "loaded" && state.chunk.element_type !== "table" && (
            <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-200">{state.chunk.content}</p>
          )}
        </div>
      </section>
    </div>
  );
}
