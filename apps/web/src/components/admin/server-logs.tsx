"use client";

import { useEffect, useState } from "react";

import { Panel, Pill } from "@/components/admin/parts";
import type { ApiClient, ServerLogEvent, ServerLogFilters, ServerLogs as Logs } from "@/lib/api";

const SERVICES: [ServerLogFilters["service"], string][] = [
  ["all", "All services"],
  ["api", "API"],
  ["agent-worker", "Agent worker"],
  ["ingest-worker", "Ingest worker"],
  ["gateway", "Data gateway"],
];
const WINDOWS: [ServerLogFilters["window"], string][] = [
  ["15m", "Last 15 min"],
  ["1h", "Last hour"],
  ["6h", "Last 6 hours"],
  ["24h", "Last 24 hours"],
];
const LEVELS: [ServerLogFilters["level"], string][] = [
  ["all", "All levels"],
  ["warning", "Warnings and errors"],
  ["error", "Errors only"],
];

const SELECT =
  "rounded-md border border-black/10 bg-transparent px-2 py-1 text-xs dark:border-white/10 dark:bg-neutral-900";

function LevelPill({ level }: { level: string | null }) {
  if (!level) return <span className="text-neutral-400">—</span>;
  const tone = level === "ERROR" || level === "CRITICAL" ? "bad" : level === "WARNING" ? "warn" : "muted";
  return <Pill tone={tone}>{level}</Pill>;
}

function Row({ event }: { event: ServerLogEvent }) {
  const [open, setOpen] = useState(false);
  const extra = event.details ? JSON.stringify(event.details, null, 2) : null;
  return (
    <li className="border-t border-black/[0.05] py-1.5 dark:border-white/[0.06]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="grid w-full grid-cols-[9.5rem_6.5rem_5.5rem_1fr] items-start gap-2 text-left text-[11px] hover:bg-black/[0.02] dark:hover:bg-white/[0.03]"
      >
        <span className="font-mono tabular-nums text-neutral-500">{event.time.slice(5, 19)} UTC</span>
        <span className="truncate text-neutral-600 dark:text-neutral-300">{event.service}</span>
        <span>
          <LevelPill level={event.level} />
        </span>
        <span className={`font-mono text-neutral-800 dark:text-neutral-200 ${open ? "whitespace-pre-wrap break-words" : "truncate"}`}>
          {event.message}
        </span>
      </button>
      {open && (event.logger || extra) && (
        <pre className="ml-[22rem] mt-1 max-h-60 overflow-auto rounded bg-neutral-50 p-2 font-mono text-[10px] text-neutral-600 dark:bg-neutral-900 dark:text-neutral-400">
          {[event.logger ? `logger: ${event.logger}` : "", extra ?? ""].filter(Boolean).join("\n")}
        </pre>
      )}
    </li>
  );
}

/** Server logs from CloudWatch, newest first. Loads on demand (filters or Refresh), never on
 * the System tab's 30-second timer, so it doesn't run a log search every half minute. */
export function ServerLogs({ api }: { api: ApiClient }) {
  const [filters, setFilters] = useState<ServerLogFilters>({
    service: "all",
    window: "1h",
    level: "all",
    text: "",
    health: false,
  });
  const [draft, setDraft] = useState("");
  const [logs, setLogs] = useState<Logs | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [run, setRun] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .adminLogs(filters)
      .then((l) => !cancelled && setLogs(l))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "Could not load logs"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [api, filters, run]);

  const set = <K extends keyof ServerLogFilters>(key: K, value: ServerLogFilters[K]) =>
    setFilters((f) => ({ ...f, [key]: value }));

  return (
    <Panel
      title="Server logs"
      subtitle="The demo machine's services, newest first (kept 14 days). Click a line for its details."
      actions={
        <button
          type="button"
          onClick={() => setRun((n) => n + 1)}
          disabled={loading}
          className="shrink-0 rounded border border-neutral-300 px-2 py-0.5 text-[11px] hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
        >
          {loading ? "Loading…" : "Refresh"}
        </button>
      }
    >
      <form
        className="mb-2 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          set("text", draft.trim());
        }}
      >
        <select aria-label="Service" className={SELECT} value={filters.service} onChange={(e) => set("service", e.target.value as ServerLogFilters["service"])}>
          {SERVICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Period" className={SELECT} value={filters.window} onChange={(e) => set("window", e.target.value as ServerLogFilters["window"])}>
          {WINDOWS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Level" className={SELECT} value={filters.level} onChange={(e) => set("level", e.target.value as ServerLogFilters["level"])}>
          {LEVELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <input
          aria-label="Search the logs"
          placeholder="Search text, e.g. a run id"
          maxLength={100}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          className={`${SELECT} min-w-48 flex-1`}
        />
        <button type="submit" className="rounded border border-neutral-300 px-2 py-1 text-[11px] hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800">
          Search
        </button>
        <label className="flex items-center gap-1.5 text-[11px] text-neutral-600 dark:text-neutral-400">
          <input type="checkbox" checked={filters.health} onChange={(e) => set("health", e.target.checked)} />
          Show health checks
        </label>
      </form>
      {error && <p className="py-2 text-xs text-red-600 dark:text-red-400">{error}</p>}
      {!error && logs && !logs.available && <p className="py-2 text-xs text-neutral-500">{logs.reason ?? "Server logs are not available here."}</p>}
      {!error && logs?.available && logs.events.length === 0 && (
        <p className="py-4 text-center text-xs text-neutral-400">No log lines match in this period.</p>
      )}
      {!error && logs?.available && logs.events.length > 0 && (
        <>
          <ul className="max-h-[32rem] overflow-y-auto">
            {logs.events.map((e, i) => (
              <Row key={`${e.time}-${i}`} event={e} />
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-neutral-400">
            {logs.events.length} line{logs.events.length === 1 ? "" : "s"}
            {logs.limit && logs.events.length >= logs.limit ? ` (the newest ${logs.limit}; narrow the filters to see older ones)` : ""}
          </p>
        </>
      )}
    </Panel>
  );
}
