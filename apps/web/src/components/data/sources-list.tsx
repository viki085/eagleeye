"use client";

import { EmptyNote } from "@/components/documents/panel-section";
import type { DataSource } from "@/lib/api";

interface SourcesListProps {
  sources: readonly DataSource[] | null;
}

/** What data the user can ask about (granted tables only). */
export function SourcesList({ sources }: SourcesListProps) {
  if (sources === null) return <EmptyNote>Loading…</EmptyNote>;
  if (sources.length === 0) {
    return <EmptyNote>No databases are available to you.</EmptyNote>;
  }
  return (
    <div className="flex flex-col px-2">
      {sources.map((s) => (
        <details key={s.id} className="py-1 text-xs" open={sources.length === 1}>
          <summary className="cursor-pointer text-neutral-800 dark:text-neutral-200">
            <span className="font-medium">{s.name}</span>
            <span className="ml-1 text-neutral-400">· {s.tables.length} tables</span>
          </summary>
          <p className="mt-1 text-[11px] text-neutral-500">{s.description}</p>
          <ul className="mt-1 flex flex-col gap-1">
            {s.tables.map((t) => (
              <li key={t.name} title={t.description}>
                <code className="text-[11px] text-neutral-700 dark:text-neutral-300">{t.name}</code>
                {t.row_estimate !== null && (
                  <span className="ml-1 text-[10px] text-neutral-400">
                    ~{t.row_estimate.toLocaleString("en-US")} rows
                  </span>
                )}
              </li>
            ))}
          </ul>
          {!s.can_see_pii && (
            <p className="mt-1 text-[10px] text-neutral-400">Personal data columns are hidden for your role.</p>
          )}
        </details>
      ))}
    </div>
  );
}
