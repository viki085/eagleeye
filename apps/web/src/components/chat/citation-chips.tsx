"use client";

import type { Citation } from "@/lib/api";

interface CitationChipsProps {
  citations: readonly Citation[];
  onOpen: (citation: Citation) => void;
}

export function CitationChips({ citations, onOpen }: CitationChipsProps) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Sources">
      {citations.map((c) => (
        <button
          key={`${c.n}-${c.chunk_id}`}
          onClick={() => onOpen(c)}
          title={c.snippet}
          className="flex max-w-xs items-center gap-1 rounded-full border border-neutral-300 bg-white px-2 py-0.5 text-[11px] text-neutral-700 hover:border-blue-500 hover:text-blue-700 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:text-blue-300"
        >
          <span className="font-semibold">[{c.n}]</span>
          <span className="truncate">{c.title}</span>
          {c.page !== null && <span className="text-neutral-400">· p.{c.page}</span>}
        </button>
      ))}
    </div>
  );
}
