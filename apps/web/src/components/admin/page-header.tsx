"use client";

import { Icon } from "@/components/admin/icons";
import type { AdminRange } from "@/lib/api";

const RANGES: { value: AdminRange; label: string; long: string }[] = [
  { value: "1h", label: "1h", long: "Last hour, by the minute" },
  { value: "24h", label: "24h", long: "Last 24 hours" },
  { value: "7d", label: "7d", long: "Last 7 days" },
  { value: "14d", label: "14d", long: "Last 14 days" },
  { value: "30d", label: "30d", long: "Last 30 days" },
];

/** Report title, the period filter (segmented, as in BI tools), a manual refresh and "Live"
 * (refresh every 5 seconds, e.g. to watch a load test). */
export function PageHeader({ title, description, range, onRange, onRefresh, refreshedAt, live = false, onLive }: {
  title: string;
  description: string;
  range: AdminRange | null; // null: this report has no period
  onRange: (r: AdminRange) => void;
  onRefresh: () => void;
  refreshedAt: Date;
  live?: boolean;
  onLive?: (on: boolean) => void;
}) {
  const time = refreshedAt.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-neutral-900 [text-wrap:balance] dark:text-neutral-50">{title}</h1>
        <p className="mt-0.5 text-xs text-neutral-500">{description}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {range && (
          <div role="radiogroup" aria-label="Reporting period" className="flex rounded-full bg-neutral-200/80 p-1 text-sm dark:bg-[#1a1a19]">
            {RANGES.map((r) => {
              const on = r.value === range;
              return (
                <button
                  key={r.value}
                  type="button"
                  role="radio"
                  aria-checked={on}
                  aria-label={r.long}
                  title={r.long}
                  onClick={() => onRange(r.value)}
                  className={`rounded-full px-3.5 py-1 font-semibold ${
                    on
                      ? "bg-white text-neutral-900 shadow-sm dark:bg-neutral-700 dark:text-white"
                      : "text-neutral-600 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
                  }`}
                >
                  {r.label}
                </button>
              );
            })}
          </div>
        )}
        {onLive && (
          <button
            type="button"
            aria-pressed={live}
            title={live ? "Live: refreshing every 5 seconds" : "Refresh every 5 seconds"}
            onClick={() => onLive(!live)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold ${
              live
                ? "border-[#0ca30c]/40 bg-[#0ca30c]/10 text-[#006300] dark:text-[#3ddc84]"
                : "border-black/10 bg-white text-neutral-700 hover:bg-black/[0.03] dark:border-white/10 dark:bg-[#1a1a19] dark:text-neutral-300"
            }`}
          >
            <span aria-hidden className={`h-2 w-2 rounded-full ${live ? "animate-pulse bg-[#0ca30c]" : "bg-neutral-400"}`} />
            Live
          </button>
        )}
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex items-center gap-1.5 rounded-lg border border-black/10 bg-white px-2.5 py-1.5 text-xs text-neutral-700 hover:bg-black/[0.03] dark:border-white/10 dark:bg-[#1a1a19] dark:text-neutral-300 dark:hover:bg-white/[0.05]"
        >
          <Icon name="refresh" className="h-3.5 w-3.5" />
          Refresh
          <span className="text-neutral-400">· {time}</span>
        </button>
      </div>
    </div>
  );
}
