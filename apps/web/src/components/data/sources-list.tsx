"use client";

import { useState } from "react";

import { EmptyNote } from "@/components/documents/panel-section";
import type { DataSource, DataSourceColumn, DataSourceTable } from "@/lib/api";
import { filterSources, tableKey } from "@/lib/doc-search";

interface SourcesListProps {
  sources: readonly DataSource[] | null;
  query?: string;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`inline-block w-3 shrink-0 text-[9px] text-neutral-400 transition-transform ${open ? "rotate-90" : ""}`}
    >
      ▶
    </span>
  );
}

function useToggles(): [ReadonlySet<string>, (key: string) => void] {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  return [open, toggle];
}

/**
 * The databases the user can ask about, as a tree: database → tables → columns. Only granted
 * tables appear; personal-data columns hidden for the user's role are marked. A search query
 * filters the tree and expands the branches that contain matches.
 */
export function SourcesList({ sources, query = "" }: SourcesListProps) {
  const [opened, toggle] = useToggles();
  if (sources === null) return <EmptyNote>Loading…</EmptyNote>;
  if (sources.length === 0) return <EmptyNote>No databases are available to you.</EmptyNote>;
  const searching = query.trim().length > 0;
  const { sources: shown, expanded } = filterSources(sources, query);
  if (shown.length === 0) return <EmptyNote>No databases, tables or columns match “{query.trim()}”.</EmptyNote>;
  const isOpen = (key: string) => (searching ? expanded.has(key) !== opened.has(key) : opened.has(key));

  return (
    <ul role="tree" aria-label="Databases" className="px-1 text-xs">
      {shown.map((s) => {
        // a single database starts expanded; clicking flips it like any other node
        const open = !searching && shown.length === 1 ? !opened.has(s.id) : isOpen(s.id);
        return (
          <li key={s.id} role="treeitem" aria-expanded={open} aria-selected={false}>
            <button
              type="button"
              onClick={() => toggle(s.id)}
              className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left hover:bg-neutral-100 dark:hover:bg-neutral-800/60"
            >
              <Chevron open={open} />
              <span className="truncate font-medium text-neutral-800 dark:text-neutral-200">{s.name}</span>
              <span className="ml-auto shrink-0 text-[10px] tabular-nums text-neutral-400">{s.tables.length} tables</span>
            </button>
            {open && (
              <div className="ml-3 border-l border-neutral-200 pl-1 dark:border-neutral-800">
                {s.description && (
                  <p title={s.description} className="line-clamp-2 px-1.5 py-1 text-[11px] text-neutral-500">
                    {s.description}
                  </p>
                )}
                <ul role="group">
                  {s.tables.map((t) => (
                    <TableNode
                      key={t.name}
                      table={t}
                      open={isOpen(tableKey(s.id, t.name))}
                      onToggle={() => toggle(tableKey(s.id, t.name))}
                    />
                  ))}
                </ul>
                {!s.can_see_pii && (
                  <p className="px-1.5 py-1 text-[10px] text-neutral-400">Personal data columns are hidden for your role.</p>
                )}
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function TableNode({ table, open, onToggle }: { table: DataSourceTable; open: boolean; onToggle: () => void }) {
  return (
    <li role="treeitem" aria-expanded={open} aria-selected={false}>
      <button
        type="button"
        onClick={onToggle}
        title={table.description}
        className="flex w-full items-center gap-1.5 rounded px-1.5 py-0.5 text-left hover:bg-neutral-100 dark:hover:bg-neutral-800/60"
      >
        <Chevron open={open} />
        <code className="truncate text-[11px] text-neutral-700 dark:text-neutral-300">{table.name}</code>
        {table.row_estimate !== null && (
          <span className="ml-auto shrink-0 text-[10px] tabular-nums text-neutral-400">
            ~{table.row_estimate.toLocaleString("en-US")}
          </span>
        )}
      </button>
      {open && (
        <div className="ml-3 border-l border-neutral-200 pl-1 dark:border-neutral-800">
          {table.description && (
            <p title={table.description} className="line-clamp-2 px-1.5 pb-1 pt-0.5 text-[11px] text-neutral-500">
              {table.description}
            </p>
          )}
          <ul role="group">
            {table.columns.map((c) => (
              <ColumnNode key={c.name} column={c} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

function ColumnNode({ column }: { column: DataSourceColumn }) {
  return (
    <li role="treeitem" aria-selected={false} title={column.description} className="flex items-baseline gap-1.5 px-1.5 py-0.5 pl-5">
      <code className={`truncate text-[11px] ${column.masked ? "text-neutral-400 line-through" : "text-neutral-700 dark:text-neutral-300"}`}>
        {column.name}
      </code>
      <span className="shrink-0 text-[10px] text-neutral-400">{column.type}</span>
      {column.pii && (
        <span className="ml-auto shrink-0 rounded bg-amber-100 px-1 text-[9px] font-medium text-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {column.masked ? "hidden" : "personal"}
        </span>
      )}
    </li>
  );
}
