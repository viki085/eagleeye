"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { DATASETS_CHANGED } from "@/hooks/use-datasets";
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

interface PictureProps {
  api: ApiClient;
  documentId: string;
  chunkId: string;
  kind: "image" | "page";
}

/** A cited figure, or the cited page with the passage marked: fetched with the bearer token,
 * shown from a blob URL (revoked on close). */
function ChunkPicture({ api, documentId, chunkId, kind }: PictureProps) {
  const [src, setSrc] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    api
      .getChunkImage(documentId, chunkId, kind)
      .then((blob) => {
        if (cancelled) return;
        url = URL.createObjectURL(blob);
        setSrc(url);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, documentId, chunkId, kind]);

  const what = kind === "page" ? "page" : "figure";
  if (failed) return <p className="mb-3 text-xs text-neutral-400">The {what} could not be loaded.</p>;
  if (src === null) return <p className="mb-3 text-xs text-neutral-400">Loading {what}…</p>;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- a blob URL, not an optimisable asset
    <img
      src={src}
      alt={kind === "page" ? "The page, with the cited passage highlighted" : "Figure from the document"}
      className="mb-3 w-full rounded-md border border-neutral-200 bg-white dark:border-neutral-800"
    />
  );
}

type SaveState = { kind: "idle" } | { kind: "saving" } | { kind: "done"; text: string } | { kind: "error"; text: string };

/** "Use as data file": the cited table becomes a CSV data file the analysis tools can work on. */
function UseAsDataFile({ api, documentId, chunkId }: Omit<PictureProps, "kind">) {
  const [state, setState] = useState<SaveState>({ kind: "idle" });

  const save = () => {
    setState({ kind: "saving" });
    api
      .datasetFromTable(documentId, chunkId)
      .then((ds) => {
        window.dispatchEvent(new Event(DATASETS_CHANGED));
        const text = ds.existing
          ? `Already saved as the data file “${ds.title}”.`
          : `Saved as the data file “${ds.title}”. Ask a question about it once it is ready.`;
        setState({ kind: "done", text });
      })
      .catch((e: unknown) =>
        setState({ kind: "error", text: e instanceof Error ? e.message : "Could not save the table" }),
      );
  };

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
      <button
        onClick={save}
        disabled={state.kind === "saving" || state.kind === "done"}
        className="rounded-md border border-neutral-300 px-2 py-1 font-medium hover:bg-neutral-50 disabled:opacity-60 dark:border-neutral-700 dark:hover:bg-neutral-900"
      >
        {state.kind === "saving" ? "Saving…" : "Use as data file"}
      </button>
      {state.kind === "done" && <span className="text-neutral-500" role="status">{state.text}</span>}
      {state.kind === "error" && <span className="text-red-600" role="alert">{state.text}</span>}
    </div>
  );
}

/** "Show on page": the page picture is only fetched when asked for (it is rendered on demand). */
function PageView({ api, documentId, chunkId, page }: Omit<PictureProps, "kind"> & { page: number | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-4 border-t border-neutral-200 pt-3 dark:border-neutral-800">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="text-xs font-medium text-blue-600 hover:underline dark:text-blue-400"
      >
        {open ? "Hide page" : `Show on page${page !== null ? ` ${page}` : ""}`}
      </button>
      {open && (
        <div className="mt-2">
          <ChunkPicture api={api} documentId={documentId} chunkId={chunkId} kind="page" />
        </div>
      )}
    </div>
  );
}

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
          {state.kind === "loaded" && state.chunk.element_type === "table" && (
            <UseAsDataFile
              key={citation.chunk_id}
              api={api}
              documentId={citation.document_id}
              chunkId={citation.chunk_id}
            />
          )}
          {state.kind === "loaded" && state.chunk.has_image && (
            <ChunkPicture api={api} documentId={citation.document_id} chunkId={citation.chunk_id} kind="image" />
          )}
          {state.kind === "loaded" && state.chunk.element_type !== "table" && (
            <p className="whitespace-pre-wrap text-neutral-800 dark:text-neutral-200">{state.chunk.content}</p>
          )}
          {state.kind === "loaded" && state.chunk.has_page && (
            <PageView
              key={citation.chunk_id}
              api={api}
              documentId={citation.document_id}
              chunkId={citation.chunk_id}
              page={state.chunk.page}
            />
          )}
        </div>
      </section>
    </div>
  );
}
