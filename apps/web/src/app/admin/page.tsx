"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ContentTab } from "@/components/admin/content-tab";
import { NotAuthorised } from "@/components/admin/parts";
import { OverviewTab } from "@/components/admin/overview-tab";
import { SafetyTab } from "@/components/admin/safety-tab";
import { SystemTab } from "@/components/admin/system-tab";
import { UsageTab } from "@/components/admin/usage-tab";
import { UsersTab } from "@/components/admin/users-tab";
import { ThemeToggle } from "@/components/theme-toggle";
import { useApi } from "@/hooks/use-api";
import { ApiError, type AdminRange } from "@/lib/api";

const TABS = [
  { id: "overview", label: "Overview", ranged: true },
  { id: "users", label: "Users", ranged: true },
  { id: "usage", label: "Usage & cost", ranged: true },
  { id: "safety", label: "Quality & safety", ranged: true },
  { id: "content", label: "Content", ranged: false },
  { id: "system", label: "System & controls", ranged: false },
] as const;
type TabId = (typeof TABS)[number]["id"];
const RANGES: { value: AdminRange; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

// A failed check (rate limit, API down) is an error with a retry, never "Not authorised":
// only a real non-admin role (or a 403) means denied.
type Access =
  | { kind: "checking" }
  | { kind: "admin" }
  | { kind: "denied" }
  | { kind: "error"; message: string };

export default function AdminPage() {
  const api = useApi();
  const [access, setAccess] = useState<Access>({ kind: "checking" });
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<TabId>("overview");
  const [range, setRange] = useState<AdminRange>("7d");

  useEffect(() => {
    let cancelled = false;
    setAccess({ kind: "checking" });
    api
      .getMe()
      .then((me) => {
        if (!cancelled) setAccess({ kind: me.role === "admin" ? "admin" : "denied" });
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 403) setAccess({ kind: "denied" });
        else setAccess({ kind: "error", message: e instanceof Error ? e.message : "Could not check access." });
      });
    return () => {
      cancelled = true;
    };
  }, [api, attempt]);

  const ranged = TABS.find((t) => t.id === tab)?.ranged ?? false;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-neutral-200 px-4 py-2.5 dark:border-neutral-800">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold tracking-tight">EagleEye</span>
          <nav aria-label="Switch between chat and admin console" className="grid grid-cols-2 rounded-lg border border-neutral-300 p-0.5 text-xs dark:border-neutral-700">
            <Link href="/" className="rounded-md px-2 py-1 text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
              Chat
            </Link>
            <span aria-current="page" className="rounded-md bg-neutral-200 px-2 py-1 font-medium dark:bg-neutral-800">
              Admin console
            </span>
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <UserButton />
        </div>
      </header>

      {access.kind === "checking" && <p className="p-6 text-sm text-neutral-400">Checking access…</p>}
      {access.kind === "denied" && (
        <div className="mx-auto mt-10 w-full max-w-md px-4">
          <NotAuthorised />
        </div>
      )}
      {access.kind === "error" && (
        <div role="alert" className="mx-auto mt-10 w-full max-w-md rounded-lg border border-neutral-200 p-6 text-center dark:border-neutral-800">
          <p className="text-sm text-red-600 dark:text-red-400">{access.message}</p>
          <button
            onClick={() => setAttempt((n) => n + 1)}
            className="mt-3 rounded border border-neutral-300 px-2.5 py-1 text-xs hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Try again
          </button>
        </div>
      )}
      {access.kind === "admin" && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-200 px-4 py-2 dark:border-neutral-800">
            <div role="tablist" aria-label="Console sections" className="flex flex-wrap gap-1">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={tab === t.id}
                  onClick={() => setTab(t.id)}
                  className={`rounded-md px-2.5 py-1 text-xs ${
                    tab === t.id
                      ? "bg-neutral-200 font-medium dark:bg-neutral-800"
                      : "text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800 dark:hover:bg-neutral-900 dark:hover:text-neutral-200"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {ranged && (
              <label className="flex items-center gap-1.5 text-xs text-neutral-500">
                Period
                <select
                  value={range}
                  onChange={(e) => setRange(e.target.value as AdminRange)}
                  className="rounded border border-neutral-300 bg-transparent px-1.5 py-0.5 dark:border-neutral-700"
                >
                  {RANGES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
          <main className="min-h-0 flex-1 overflow-y-auto p-4">
            <div className="mx-auto max-w-7xl">
              {tab === "overview" && <OverviewTab api={api} range={range} />}
              {tab === "users" && <UsersTab api={api} range={range} />}
              {tab === "usage" && <UsageTab api={api} range={range} />}
              {tab === "safety" && <SafetyTab api={api} range={range} />}
              {tab === "content" && <ContentTab api={api} />}
              {tab === "system" && <SystemTab api={api} />}
            </div>
          </main>
        </>
      )}
    </div>
  );
}
