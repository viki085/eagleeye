"use client";

import { useEffect, useState } from "react";

import type { ApiClient, DataSource } from "@/lib/api";

interface SourcesListProps {
  api: ApiClient;
}

/** What data the user can ask about (granted tables only). */
export function SourcesList({ api }: SourcesListProps) {
  const [sources, setSources] = useState<DataSource[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .listSources()
      .then((s) => !cancelled && setSources(s))
      .catch(() => !cancelled && setSources([]));
    return () => {
      cancelled = true;
    };
  }, [api]);

  if (sources === null || sources.length === 0) return null;
  return (
    <section aria-label="Data sources" className="border-t border-neutral-200 px-3 py-3 dark:border-neutral-800">
      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-neutral-500">Data sources</h2>
      {sources.map((s) => (
        <details key={s.id} className="mt-2 text-xs">
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
    </section>
  );
}
