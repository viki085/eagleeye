"use client";

import { useState } from "react";

import { type CodeMode, formatQuery, loadFormatter } from "@/lib/format-sql";

interface SqlBlockProps {
  sql: string;
  label?: string;
  /** how to lay the code out: SQL dialects are formatted, Python is shown as written */
  mode?: CodeMode;
}

/** Collapsible, copyable code — what actually ran (validated server-side), laid out readably. */
export function SqlBlock({ sql, label = "SQL", mode = "sql" }: SqlBlockProps) {
  const [copied, setCopied] = useState(false);
  const [shown, setShown] = useState(sql);

  // formatted on first open: the formatter is loaded only when someone looks at a query
  const onToggle = (open: boolean) => {
    if (!open || shown !== sql || mode === "python") return;
    void loadFormatter()
      .then((format) => setShown(formatQuery(format, sql, mode)))
      .catch(() => undefined); // keep the query as written
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(shown);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <details
      onToggle={(e) => onToggle((e.currentTarget as HTMLDetailsElement).open)}
      className="group rounded-md border border-neutral-200 text-xs dark:border-neutral-800"
    >
      <summary className="flex cursor-pointer list-none items-center justify-between px-2.5 py-1.5 text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
        <span>
          <span className="mr-1 inline-block transition-transform group-open:rotate-90">▸</span>
          {label}
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            void copy();
          }}
          className="rounded px-1.5 py-0.5 hover:bg-neutral-100 dark:hover:bg-neutral-800"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </summary>
      <pre className="max-h-96 overflow-auto border-t border-neutral-200 bg-neutral-50 p-2.5 font-mono text-[11px] leading-relaxed text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
        {shown}
      </pre>
    </details>
  );
}
