"use client";

import { useState } from "react";

import { AddUserDialog, ROLE_INFO } from "@/components/admin/add-user-dialog";
import { ConfirmDeleteDialog } from "@/components/admin/confirm-delete-dialog";
import { ImportUsersDialog } from "@/components/admin/import-users-dialog";
import { PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/admin/modal";
import { DataTable, Panel, Pill, SectionState, type Column } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { count, money, when } from "@/lib/admin-format";
import type { AdminRange, AdminUserRow, AdminUserSort, ApiClient, UserRole } from "@/lib/api";

const PAGE = 50;
const SORTS: { value: AdminUserSort; label: string }[] = [
  { value: "last_seen", label: "Last seen" },
  { value: "cost", label: "Cost" },
  { value: "runs", label: "Requests" },
  { value: "email", label: "Email" },
];

function roleLabel(role: string): string {
  return ROLE_INFO[role as UserRole]?.label ?? role;
}

function columns(meId: string | null, onDelete: (u: AdminUserRow) => void): Column<AdminUserRow>[] {
  return [
    {
      key: "email",
      label: "User",
      render: (u) => (
        <span className="flex flex-col">
          <span className="font-medium">{u.email}</span>
          {(u.display_name || u.username) && (
            <span className="text-[11px] text-neutral-500">
              {u.display_name}
              {u.display_name && u.username && " · "}
              {u.username && <span className="font-mono">@{u.username}</span>}
            </span>
          )}
        </span>
      ),
    },
    { key: "role", label: "Role", render: (u) => <Pill tone={u.role === "admin" ? "warn" : "muted"}>{roleLabel(u.role)}</Pill> },
    { key: "status", label: "Status", render: (u) => <Pill tone={u.status === "active" ? "ok" : "bad"}>{u.status}</Pill> },
    { key: "seen", label: "Last seen", render: (u) => (u.last_seen_at ? when(u.last_seen_at) : <span className="text-neutral-400">Not signed in yet</span>) },
    { key: "runs", label: "Requests", numeric: true, render: (u) => count(u.runs) },
    { key: "tokens", label: "Tokens", numeric: true, render: (u) => count(u.tokens) },
    { key: "cost", label: "Cost (period)", numeric: true, render: (u) => money(u.cost_usd, 4) },
    { key: "limit", label: "Usage limit used", numeric: true, render: (u) => (u.limit_used_pct === null ? "—" : `${u.limit_used_pct}%`) },
    {
      key: "actions",
      label: "",
      render: (u) =>
        u.id === meId ? (
          <span className="text-[11px] text-neutral-400">You</span>
        ) : (
          <button
            type="button"
            onClick={() => onDelete(u)}
            aria-label={`Delete ${u.email}`}
            className="rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
          >
            Delete
          </button>
        ),
    },
  ];
}

export function UsersTab({ api, range, refreshKey, meId }: {
  api: ApiClient;
  range: AdminRange;
  refreshKey: number;
  meId: string | null;
}) {
  const [sort, setSort] = useState<AdminUserSort>("last_seen");
  const [offset, setOffset] = useState(0);
  const [dialog, setDialog] = useState<"add" | "import" | null>(null);
  const [toDelete, setToDelete] = useState<AdminUserRow | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [state, reload] = useAdminData(
    () => api.adminUsers(range, sort, offset),
    [api, range, sort, offset, refreshKey],
  );

  async function confirmDelete(): Promise<void> {
    if (!toDelete) return;
    await api.deleteUser(toDelete.id);
    setNotice(`${toDelete.email} was deleted and can no longer sign in.`);
    reload();
  }

  return (
    <>
      <SectionState state={state}>
        {(d) => (
          <Panel
            title={`Users (${count(d.total)})`}
            subtitle="Only people you add here can sign in. There is no self-signup."
            actions={
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
                  Sort by
                  <select
                    value={sort}
                    onChange={(e) => {
                      setSort(e.target.value as AdminUserSort);
                      setOffset(0);
                    }}
                    className="rounded border border-black/15 bg-transparent px-1 py-0.5 dark:border-white/15"
                  >
                    {SORTS.map((s) => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                </label>
                <button type="button" onClick={() => setDialog("import")} className={SECONDARY_BUTTON}>Import CSV</button>
                <button type="button" onClick={() => setDialog("add")} className={PRIMARY_BUTTON}>+ Add user</button>
              </div>
            }
          >
            {notice && (
              <p role="status" className="mb-2 rounded-md bg-[#0ca30c]/10 px-3 py-1.5 text-xs text-[#006300] dark:text-[#0ca30c]">
                {notice}
              </p>
            )}
            <DataTable rows={d.items} columns={columns(meId, setToDelete)} empty="No users yet." />
            <footer className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-neutral-500">
              <span>
                Requests, tokens and cost cover the selected period; the usage limit ({money(d.usage_limit_usd, 0)}) is
                lifetime. Chat content is never shown here.
              </span>
              <span className="flex gap-1.5">
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className={SECONDARY_BUTTON}>
                  Previous
                </button>
                <button type="button" disabled={offset + PAGE >= d.total} onClick={() => setOffset(offset + PAGE)} className={SECONDARY_BUTTON}>
                  Next
                </button>
              </span>
            </footer>
          </Panel>
        )}
      </SectionState>
      <AddUserDialog
        api={api}
        open={dialog === "add"}
        onClose={() => setDialog(null)}
        onAdded={(u) => {
          setNotice(
            `${u.email} was added as ${roleLabel(u.role)}.` +
              (u.username ? ` They can sign in now as "${u.username}" or with their email.` : " They can sign in now."),
          );
          reload();
        }}
      />
      <ImportUsersDialog api={api} open={dialog === "import"} onClose={() => setDialog(null)} onImported={reload} />
      <ConfirmDeleteDialog
        names={toDelete ? [toDelete.email] : null}
        consequence="They lose access to EagleEye immediately. Their history is kept for audit and billing; adding the same email again restores the account."
        onConfirm={confirmDelete}
        onClose={() => setToDelete(null)}
      />
    </>
  );
}
