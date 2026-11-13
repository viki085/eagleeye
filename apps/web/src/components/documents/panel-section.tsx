"use client";

import type { ReactNode } from "react";

interface PanelSectionProps {
  title: string;
  count?: number;
  hint?: ReactNode;
  children: ReactNode;
}

/**
 * One third of the right panel: a fixed header and a list that scrolls on its own, so
 * documents, data files and data sources always stay visible together.
 */
export function PanelSection({ title, count, hint, children }: PanelSectionProps) {
  return (
    <section aria-label={title} className="flex min-h-0 flex-1 basis-0 flex-col">
      <header className="flex items-baseline justify-between px-3 pb-1 pt-2.5">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">
          {title}
        </h2>
        {count !== undefined && count > 0 && (
          <span className="text-[11px] tabular-nums text-neutral-400">{count}</span>
        )}
      </header>
      {hint && <div className="px-3 pb-1 text-[11px] text-neutral-500">{hint}</div>}
      <div className="min-h-0 flex-1 overflow-y-auto px-1 pb-2">{children}</div>
    </section>
  );
}

export function EmptyNote({ children }: { children: ReactNode }) {
  return <p className="px-2 py-2 text-xs text-neutral-400">{children}</p>;
}
