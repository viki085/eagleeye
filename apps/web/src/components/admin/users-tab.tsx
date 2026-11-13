"use client";

import { useState } from "react";

import { DataTable, Panel, Pill, SectionState, type Column } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { count, money, when } from "@/lib/admin-format";
import type { AdminRange, AdminUserRow, AdminUserSort, ApiClient } from "@/lib/api";

const PAGE = 50;
const SORTS: { value: AdminUserSort; label: string }[] = [
  { value: "last_seen", label: "Last seen" },
  { value: "cost", label: "Cost" },
  { value: "runs", label: "Answers" },
  { value: "email", label: "Email" },
];

const COLUMNS: Column<AdminUserRow>[] = [
  { key: "email", label: "User", render: (u) => <span className="font-medium">{u.email}</span> },
  {
    key: "role",
    label: "Role",
    render: (u) => <Pill tone={u.role === "admin" ? "warn" : "muted"}>{u.role}</Pill>,
  },
  {
    key: "status",
    label: "Status",
    render: (u) => <Pill tone={u.status === "active" ? "ok" : "bad"}>{u.status}</Pill>,
  },
  { key: "seen", label: "Last seen", render: (u) => when(u.last_seen_at) },
  { key: "runs", label: "Answers", numeric: true, render: (u) => count(u.runs) },
  { key: "tokens", label: "Tokens", numeric: true, render: (u) => count(u.tokens) },
  { key: "cost", label: "Cost (period)", numeric: true, render: (u) => money(u.cost_usd, 4) },
  {
    key: "limit",
    label: "Usage limit used",
    numeric: true,
    render: (u) => (u.limit_used_pct === null ? "—" : `${u.limit_used_pct}%`),
  },
];

export function UsersTab({ api, range }: { api: ApiClient; range: AdminRange }) {
  const [sort, setSort] = useState<AdminUserSort>("last_seen");
  const [offset, setOffset] = useState(0);
  const [state] = useAdminData(() => api.adminUsers(range, sort, offset), [api, range, sort, offset]);
  return (
    <SectionState state={state}>
      {(d) => (
        <Panel
          title={`Users (${count(d.total)})`}
          actions={
            <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
              Sort by
              <select
                value={sort}
                onChange={(e) => {
                  setSort(e.target.value as AdminUserSort);
                  setOffset(0);
                }}
                className="rounded border border-neutral-300 bg-transparent px-1 py-0.5 dark:border-neutral-700"
              >
                {SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
          }
        >
          <DataTable rows={d.items} columns={COLUMNS} empty="No users yet." />
          <footer className="mt-2 flex items-center justify-between text-[11px] text-neutral-500">
            <span>
              Answers, tokens and cost cover the selected period; the usage limit
              ({money(d.usage_limit_usd, 0)}) is lifetime. Chat content is never shown here.
            </span>
            <span className="flex gap-1.5">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - PAGE))}
                className="rounded border border-neutral-300 px-2 py-0.5 disabled:opacity-40 dark:border-neutral-700"
              >
                Previous
              </button>
              <button
                type="button"
                disabled={offset + PAGE >= d.total}
                onClick={() => setOffset(offset + PAGE)}
                className="rounded border border-neutral-300 px-2 py-0.5 disabled:opacity-40 dark:border-neutral-700"
              >
                Next
              </button>
            </span>
          </footer>
        </Panel>
      )}
    </SectionState>
  );
}
