"use client";

import { useEffect, useState } from "react";

import { SqlBlock } from "@/components/data/sql-block";
import type { ArtifactView } from "@/lib/api";
import {
  cellSummary,
  notebookTableArtifact,
  type NotebookCell,
  type NotebookTable,
  type NotebookView,
} from "@/lib/notebook";

const BUTTON =
  "rounded-md border border-neutral-300 px-2 py-0.5 text-[11px] text-neutral-600 hover:bg-neutral-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800";
const PREVIEW_ROWS = 6;

export type FigureLoader = (notebookId: string, name: string) => Promise<Blob>;

interface NotebookCardProps {
  notebook: NotebookView;
  loadFigure: FigureLoader;
  onDownload: (notebook: NotebookView) => void;
  onViewTable?: (artifact: ArtifactView) => void;
}

/** One figure, fetched with the user's token and shown from a blob URL; click to enlarge. */
function Figure({ notebookId, name, load, onOpen }: {
  notebookId: string;
  name: string;
  load: FigureLoader;
  onOpen: (url: string) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    load(notebookId, name)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [notebookId, name, load]);
  if (failed) {
    return <div className="grid h-40 place-items-center rounded-md bg-neutral-100 text-xs text-neutral-500 dark:bg-neutral-900">Figure unavailable</div>;
  }
  if (!url) return <div className="h-40 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-900" aria-label="Loading figure" />;
  return (
    <button type="button" onClick={() => onOpen(url)} className="block overflow-hidden rounded-md border border-neutral-200 bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400 dark:border-neutral-800" aria-label={`Enlarge ${name}`}>
      {/* eslint-disable-next-line @next/next/no-img-element -- blob URL from an authenticated fetch */}
      <img src={url} alt={`Notebook figure ${name}`} className="h-auto w-full" />
    </button>
  );
}

/** Previews round long decimals; the full values are in "Open table" and the CSV export. */
function previewValue(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number" && !Number.isInteger(v)) return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return String(v);
}

function TablePreview({ table, onView }: { table: NotebookTable; onView?: () => void }) {
  const rows = table.preview.slice(0, PREVIEW_ROWS);
  return (
    <div className="rounded-md border border-neutral-200 dark:border-neutral-800">
      <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-xs">
        <span className="font-medium text-neutral-700 dark:text-neutral-200">
          {table.title.replace(/_/g, " ")} <span className="font-normal text-neutral-500">· {table.row_count.toLocaleString()} rows</span>
        </span>
        {onView && <button type="button" className={BUTTON} onClick={onView}>Open table</button>}
      </div>
      <div className="overflow-x-auto border-t border-neutral-200 dark:border-neutral-800">
        <table className="w-full text-left text-[11px] tabular-nums">
          <thead className="bg-neutral-50 text-neutral-500 dark:bg-neutral-900">
            <tr>{table.columns.map((c) => <th key={c.name} className="whitespace-nowrap px-2 py-1 font-medium">{c.name}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-neutral-100 dark:border-neutral-800/60">
                {r.map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1 text-neutral-700 dark:text-neutral-300">{previewValue(v)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Cell({ nb, cell, loadFigure, onViewTable, onOpenFigure }: {
  nb: NotebookView;
  cell: NotebookCell;
  loadFigure: FigureLoader;
  onViewTable?: (artifact: ArtifactView) => void;
  onOpenFigure: (url: string) => void;
}) {
  const stats = Object.entries(cell.stats ?? {});
  const failed = cell.status === "error";
  return (
    <li className="flex flex-col gap-2 border-t border-neutral-200 px-3 py-3 first:border-t-0 dark:border-neutral-800">
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="text-sm font-medium text-neutral-900 dark:text-neutral-100">
          <span className="mr-1.5 tabular-nums text-neutral-400">{cell.index + 1}.</span>
          {cell.purpose}
        </h4>
        <span className={`shrink-0 text-[11px] ${failed ? "text-red-600 dark:text-red-400" : "text-neutral-500"}`}>{cellSummary(cell)}</span>
      </div>
      {cell.status !== "not run" && <SqlBlock sql={cell.code} label="Python" />}
      {cell.stdout && (
        <pre className="overflow-x-auto rounded-md bg-neutral-50 p-2 font-mono text-[11px] text-neutral-700 dark:bg-neutral-900 dark:text-neutral-300">{cell.stdout}</pre>
      )}
      {cell.tables.map((t) => (
        <TablePreview key={t.artifact_id} table={t} onView={onViewTable ? () => onViewTable(notebookTableArtifact(nb, cell, t)) : undefined} />
      ))}
      {stats.length > 0 && (
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-[11px]">
          {stats.map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-neutral-500">{k.replace(/_/g, " ")}</dt>
              <dd className="tabular-nums text-neutral-800 dark:text-neutral-200">{typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: 4 }) : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {cell.figures.length > 0 && (
        <div className={`grid gap-2 ${cell.figures.length > 1 ? "sm:grid-cols-2" : ""}`}>
          {cell.figures.map((f) => <Figure key={f} notebookId={nb.notebook_id} name={f} load={loadFigure} onOpen={onOpenFigure} />)}
        </div>
      )}
      {cell.error && <p className="rounded-md bg-red-50 px-2 py-1.5 font-mono text-[11px] text-red-700 dark:bg-red-950/40 dark:text-red-300">{cell.error}</p>}
      {cell.note && <p className="text-[11px] text-neutral-500">{cell.note}</p>}
    </li>
  );
}

/** Notebook mode: an analyst-style notebook under the answer, cell by cell, with a .ipynb download. */
export function NotebookCard({ notebook, loadFigure, onDownload, onViewTable }: NotebookCardProps) {
  const [open, setOpen] = useState(true);
  const [enlarged, setEnlarged] = useState<string | null>(null);
  useEffect(() => {
    if (!enlarged) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setEnlarged(null);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enlarged]);
  const cells = notebook.cells.length;
  return (
    <section aria-label={`Notebook: ${notebook.title}`} className="mt-3 rounded-lg border border-neutral-200 dark:border-neutral-800">
      <header className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
        <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex min-w-0 items-center gap-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-400">
          <span className={`text-neutral-400 transition-transform ${open ? "rotate-90" : ""}`}>▸</span>
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-neutral-900 dark:text-neutral-100">{notebook.title}</span>
            <span className="text-[11px] text-neutral-500">
              Notebook · {cells} cell{cells === 1 ? "" : "s"} · {notebook.figure_count} figure{notebook.figure_count === 1 ? "" : "s"}
              {notebook.status !== "ok" ? " · stopped early" : ""}
            </span>
          </span>
        </button>
        <button type="button" className={BUTTON} onClick={() => onDownload(notebook)}>Download .ipynb</button>
      </header>
      {open && (
        <ol className="border-t border-neutral-200 dark:border-neutral-800">
          {notebook.cells.map((c) => (
            <Cell key={c.index} nb={notebook} cell={c} loadFigure={loadFigure} onViewTable={onViewTable} onOpenFigure={setEnlarged} />
          ))}
        </ol>
      )}
      {enlarged && (
        <div role="dialog" aria-modal="true" aria-label="Enlarged figure" className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4" onClick={() => setEnlarged(null)}>
          {/* eslint-disable-next-line @next/next/no-img-element -- blob URL from an authenticated fetch */}
          <img src={enlarged} alt="Enlarged notebook figure" className="max-h-full max-w-full rounded-md bg-white" />
        </div>
      )}
    </section>
  );
}
