/** Which cited figures and tables an answer shows under its text (pure, for the message view). */

import type { Citation } from "./api";

export const MAX_FIGURES = 3;
export const MAX_TABLES = 2;

// a Markdown table: a pipe row followed by its |---| rule
const MARKDOWN_TABLE = /^\s*\|.*\|\s*\n\s*\|[\s:|]*-[\s:|-]*\|\s*$/m;

export function hasMarkdownTable(text: string): boolean {
  return MARKDOWN_TABLE.test(text);
}

export interface SourceVisuals {
  figures: Citation[];
  tables: Citation[];
}

/**
 * Cited charts and pictures are always shown (the reader sees what the answer read). Cited
 * tables are shown only when the answer has no table of its own, so the same rows never
 * appear twice. One entry per chunk, in citation order, a few at most.
 */
export function pickVisuals(citations: readonly Citation[], answer: string): SourceVisuals {
  const seen = new Set<string>();
  const unique = citations.filter((c) => !seen.has(c.chunk_id) && seen.add(c.chunk_id));
  const figures = unique.filter((c) => c.element_type === "image").slice(0, MAX_FIGURES);
  const tables = hasMarkdownTable(answer)
    ? []
    : unique.filter((c) => c.element_type === "table").slice(0, MAX_TABLES);
  return { figures, tables };
}
