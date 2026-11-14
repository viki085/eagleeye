/** Notebook mode: the notebook payload under an answer (live event or saved message part). */

import type { ArtifactColumn, ArtifactView } from "./api";

export interface NotebookTable {
  artifact_id: string;
  title: string;
  row_count: number;
  columns: ArtifactColumn[];
  preview: unknown[][];
}

export interface NotebookCell {
  index: number;
  purpose: string;
  code: string;
  status: "ok" | "error" | "not run" | string;
  stdout: string;
  error: string;
  note: string;
  stats: Record<string, unknown>;
  figures: string[];
  tables: NotebookTable[];
}

export interface NotebookView {
  notebook_id: string;
  title: string;
  inputs: { name: string; title: string }[];
  cells: NotebookCell[];
  figure_count: number;
  status: string;
}

export function isNotebook(d: Record<string, unknown>): boolean {
  return typeof d.notebook_id === "string" && typeof d.title === "string" && Array.isArray(d.cells);
}

const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

/** "1 table · 2 figures · 3 numbers", or what the cell is when it has none of those. */
export function cellSummary(cell: NotebookCell): string {
  if (cell.status === "not run") return "not run";
  if (cell.status === "error") return "error";
  const stats = Object.keys(cell.stats ?? {}).length;
  const parts = [
    cell.tables.length ? plural(cell.tables.length, "table") : "",
    cell.figures.length ? plural(cell.figures.length, "figure") : "",
    stats ? plural(stats, "number") : "",
  ].filter(Boolean);
  if (parts.length) return parts.join(" · ");
  return cell.stdout ? "output" : "no output";
}

/** A notebook table as an artifact, so it opens in the existing table viewer and CSV export. */
export function notebookTableArtifact(nb: NotebookView, cell: NotebookCell, table: NotebookTable): ArtifactView {
  return {
    artifact_id: table.artifact_id,
    type: "table",
    title: `${nb.title} — ${table.title.replace(/_/g, " ")}`,
    sql: cell.code,
    source: `notebook: ${nb.title}`,
    columns: table.columns,
    row_count: table.row_count,
    truncated: false,
    preview: table.preview,
    assumptions: cell.purpose,
    mode: "python",
  };
}
