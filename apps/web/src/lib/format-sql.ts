/** Readable SQL for the query panel: one clause per line, indented, keywords in capitals. */

export type CodeMode = "sql" | "duckdb" | "python";

type Formatter = (sql: string, options: Record<string, unknown>) => string;

const OPTIONS = {
  tabWidth: 2,
  keywordCase: "upper",
  dataTypeCase: "upper",
  functionCase: "preserve",
  identifierCase: "preserve",
  linesBetweenQueries: 1,
  expressionWidth: 60, // short expressions stay on one line, longer ones wrap
};

/**
 * The query laid out the way a developer would write it. Python is left as written, and so is
 * anything the formatter can't parse (the original text is always the safe fallback). Only
 * whitespace and keyword case change, so the formatted query runs the same.
 */
export function formatQuery(format: Formatter, code: string, mode: CodeMode = "sql"): string {
  if (mode === "python" || !code.trim()) return code;
  try {
    return format(code, { ...OPTIONS, language: mode === "duckdb" ? "duckdb" : "postgresql" });
  } catch {
    return code;
  }
}

/** Loads the formatter only when a query is first shown (it bundles many SQL dialects). */
let loading: Promise<Formatter> | null = null;
export function loadFormatter(): Promise<Formatter> {
  loading ??= import("sql-formatter").then((m) => m.format as unknown as Formatter);
  return loading;
}
