"use client";

import { UserButton } from "@clerk/nextjs";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ConsoleNav, SECTIONS, type SectionId } from "@/components/admin/console-nav";
import { ContentTab } from "@/components/admin/content-tab";
import { OverviewTab } from "@/components/admin/overview-tab";
import { PageHeader } from "@/components/admin/page-header";
import { NotAuthorised } from "@/components/admin/parts";
import { SafetyTab } from "@/components/admin/safety-tab";
import { SystemTab } from "@/components/admin/system-tab";
import { UsageTab } from "@/components/admin/usage-tab";
import { UsersTab } from "@/components/admin/users-tab";
import { ThemeToggle } from "@/components/theme-toggle";
import { useApi } from "@/hooks/use-api";
import { ApiError, type AdminRange } from "@/lib/api";

// A failed check (rate limit, API down) is an error with a retry, never "Not authorised":
// only a real non-admin role (or a 403) means denied.
type Access =
  | { kind: "checking" }
  | { kind: "admin"; meId: string }
  | { kind: "denied" }
  | { kind: "error"; message: string };

function TopBar() {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-black/[0.08] bg-white px-4 dark:border-white/10 dark:bg-[#1a1a19]">
      <div className="flex min-w-0 items-center gap-3">
        <span className="flex items-center gap-2">
          <span aria-hidden="true" className="grid h-6 w-6 place-items-center rounded-md bg-[#2a78d6] text-[11px] font-bold text-white">E</span>
          <span className="hidden text-sm font-semibold tracking-tight sm:inline">EagleEye</span>
        </span>
        <span aria-hidden="true" className="hidden h-5 w-px bg-black/10 sm:block dark:bg-white/10" />
        <nav aria-label="Switch between chat and admin console" className="grid grid-cols-2 whitespace-nowrap rounded-lg border border-black/10 p-0.5 text-xs dark:border-white/10">
          <Link href="/" className="rounded-md px-2.5 py-1 text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
            Chat
          </Link>
          <span aria-current="page" className="rounded-md bg-neutral-900 px-2.5 py-1 font-medium text-white dark:bg-neutral-100 dark:text-neutral-900">
            Admin console
          </span>
        </nav>
      </div>
      <div className="flex items-center gap-2">
        <ThemeToggle />
        <UserButton />
      </div>
    </header>
  );
}

function useAdminAccess(api: ReturnType<typeof useApi>, attempt: number): Access {
  const [access, setAccess] = useState<Access>({ kind: "checking" });
  useEffect(() => {
    let cancelled = false;
    // re-checks (a session refresh hands us a new client) run silently: the console stays
    // on screen and only changes if the answer does
    api
      .getMe()
      .then((me) => {
        if (!cancelled) setAccess(me.role === "admin" ? { kind: "admin", meId: me.id } : { kind: "denied" });
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
  return access;
}

export default function AdminPage() {
  const api = useApi();
  const [attempt, setAttempt] = useState(0);
  const access = useAdminAccess(api, attempt);
  const [section, setSection] = useState<SectionId>("overview");
  const [range, setRange] = useState<AdminRange>("7d");
  const [refreshKey, setRefreshKey] = useState(0);
  const [refreshedAt, setRefreshedAt] = useState(() => new Date());
  const meta = SECTIONS.find((s) => s.id === section) ?? SECTIONS[0];

  function refresh(): void {
    setRefreshKey((n) => n + 1);
    setRefreshedAt(new Date());
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#f3f3f0] text-neutral-900 dark:bg-[#0d0d0d] dark:text-neutral-100">
      <TopBar />
      {access.kind === "checking" && <p className="p-6 text-sm text-neutral-400">Checking access…</p>}
      {access.kind === "denied" && (
        <div className="mx-auto mt-10 w-full max-w-md px-4">
          <NotAuthorised />
        </div>
      )}
      {access.kind === "error" && (
        <div role="alert" className="mx-auto mt-10 w-full max-w-md rounded-xl border border-black/10 bg-white p-6 text-center dark:border-white/10 dark:bg-[#1a1a19]">
          <p className="text-sm text-red-600 dark:text-red-400">{access.message}</p>
          <button
            onClick={() => setAttempt((n) => n + 1)}
            aria-label="Check access again"
            className="mt-3 rounded border border-neutral-300 px-2.5 py-1 text-xs hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-900"
          >
            Try again
          </button>
        </div>
      )}
      {access.kind === "admin" && (
        <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
          <ConsoleNav
            active={section}
            onSelect={(id) => {
              setSection(id);
              setRefreshedAt(new Date());
            }}
          />
          <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex max-w-[1600px] flex-col gap-4 px-4 py-5 lg:px-6">
              <PageHeader
                title={meta.label}
                description={meta.description}
                range={meta.ranged ? range : null}
                onRange={setRange}
                onRefresh={refresh}
                refreshedAt={refreshedAt}
              />
              {section === "overview" && <OverviewTab api={api} range={range} refreshKey={refreshKey} />}
              {section === "users" && <UsersTab api={api} range={range} refreshKey={refreshKey} meId={access.meId} />}
              {section === "usage" && <UsageTab api={api} range={range} refreshKey={refreshKey} />}
              {section === "safety" && <SafetyTab api={api} range={range} refreshKey={refreshKey} />}
              {section === "content" && <ContentTab api={api} refreshKey={refreshKey} />}
              {section === "system" && <SystemTab api={api} refreshKey={refreshKey} />}
            </div>
          </main>
        </div>
      )}
    </div>
  );
}
