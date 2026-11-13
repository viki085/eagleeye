"use client";

import { useState } from "react";

interface SqlBlockProps {
  sql: string;
  label?: string;
}

/** Collapsible, copyable code — what actually ran (validated server-side). */
export function SqlBlock({ sql, label = "SQL" }: SqlBlockProps) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  return (
    <details className="group rounded-md border border-neutral-200 text-xs dark:border-neutral-800">
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
      <pre className="overflow-x-auto border-t border-neutral-200 bg-neutral-50 p-2.5 font-mono text-[11px] leading-relaxed text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
        {sql}
      </pre>
    </details>
  );
}
