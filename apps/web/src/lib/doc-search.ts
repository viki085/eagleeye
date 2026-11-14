import type { DataSource, DataSourceTable, DocumentChunkText, DocumentSummary } from "@/lib/api";

/** Lower-case words of a search box; every word must match (AND), in any order. */
export function queryWords(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}

function matchesAll(haystack: string, words: readonly string[]): boolean {
  const text = haystack.toLowerCase();
  return words.every((w) => text.includes(w));
}

export function filterDocuments(
  docs: readonly DocumentSummary[],
  query: string,
): readonly DocumentSummary[] {
  const words = queryWords(query);
  if (words.length === 0) return docs;
  return docs.filter((d) => matchesAll(`${d.title} ${d.filename}`, words));
}

export interface SourceMatch {
  sources: DataSource[];
  /** Ids of sources and "source/table" keys to show expanded because something inside matched. */
  expanded: ReadonlySet<string>;
}

export const tableKey = (sourceId: string, table: string): string => `${sourceId}/${table}`;

function filterTable(t: DataSourceTable, words: readonly string[]): DataSourceTable | null {
  if (matchesAll(`${t.name} ${t.description}`, words)) return t; // whole table matches
  const columns = t.columns.filter((c) => matchesAll(`${c.name} ${c.description}`, words));
  return columns.length > 0 ? { ...t, columns } : null;
}

/**
 * Filters the database tree: a source whose name or description matches keeps everything; a
 * table that matches keeps all its columns; otherwise only matching columns are kept. Matches
 * below a node expand it, so results are visible without clicking.
 */
export function filterSources(sources: readonly DataSource[], query: string): SourceMatch {
  const words = queryWords(query);
  if (words.length === 0) return { sources: [...sources], expanded: new Set() };
  const expanded = new Set<string>();
  const out: DataSource[] = [];
  for (const s of sources) {
    if (matchesAll(`${s.name} ${s.description}`, words)) {
      out.push(s);
      continue;
    }
    const tables: DataSourceTable[] = [];
    for (const t of s.tables) {
      const kept = filterTable(t, words);
      if (kept === null) continue;
      tables.push(kept);
      if (kept.columns.length < t.columns.length) expanded.add(tableKey(s.id, t.name));
    }
    if (tables.length > 0) {
      out.push({ ...s, tables });
      expanded.add(s.id);
    }
  }
  return { sources: out, expanded };
}

const MAX_OVERLAP = 600;

/** Longest suffix of `a` that is also a prefix of `b` (chunk overlap), up to MAX_OVERLAP chars. */
export function overlapLength(a: string, b: string): number {
  const limit = Math.min(MAX_OVERLAP, a.length, b.length);
  for (let n = limit; n >= 20; n--) {
    if (a.endsWith(b.slice(0, n))) return n;
  }
  return 0;
}

export interface TextSection {
  heading: string | null;
  text: string;
}

/**
 * Rebuilds readable text from indexed chunks: removes the overlap each chunk repeats from the
 * previous one, and starts a new section whenever the heading changes.
 */
export function joinChunks(chunks: readonly DocumentChunkText[]): TextSection[] {
  const sections: TextSection[] = [];
  let previous = "";
  for (const c of [...chunks].sort((x, y) => x.chunk_no - y.chunk_no)) {
    const body = c.content.slice(overlapLength(previous, c.content));
    previous = c.content;
    const heading = c.heading_path.length > 0 ? c.heading_path[c.heading_path.length - 1] : null;
    const last = sections[sections.length - 1];
    if (last && last.heading === heading) {
      last.text = `${last.text}${body}`;
    } else {
      sections.push({ heading, text: body.trimStart() });
    }
  }
  return sections;
}

export type ViewerKind = "pdf" | "markdown" | "text" | "indexed";

export function viewerKind(doc: Pick<DocumentSummary, "mime" | "filename">): ViewerKind {
  const name = doc.filename.toLowerCase();
  if (doc.mime === "application/pdf" || name.endsWith(".pdf")) return "pdf";
  if (doc.mime === "text/markdown" || name.endsWith(".md") || name.endsWith(".markdown")) return "markdown";
  if (doc.mime === "text/plain" || name.endsWith(".txt")) return "text";
  return "indexed"; // Word: shown from the indexed text
}

/** Clamp a split fraction so neither section collapses below a usable height. */
export function clampSplit(fraction: number, min = 0.15): number {
  if (!Number.isFinite(fraction)) return 0.5;
  return Math.min(1 - min, Math.max(min, fraction));
}
