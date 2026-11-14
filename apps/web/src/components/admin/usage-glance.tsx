"use client";

import { useState, type ReactNode } from "react";

import { GlanceBars, GlanceLines } from "@/components/admin/glance-charts";
import { CARD } from "@/components/admin/kpi";
import { bucketLabel, count, money } from "@/lib/admin-format";
import type { AdminOverview, ApiClient, AppCacheKind } from "@/lib/api";
import { budgetState, ratios, type BudgetState } from "@/lib/spark";

const INPUT = { stroke: "stroke-[#eb6834] dark:stroke-[#d95926]", fill: "fill-[#eb6834] dark:fill-[#d95926]" };
const OUTPUT = { stroke: "stroke-[#e87ba4] dark:stroke-[#d55181]", fill: "fill-[#e87ba4] dark:fill-[#d55181]" };
const CACHE = { stroke: "stroke-[#6250d6] dark:stroke-[#9085e9]", fill: "fill-[#6250d6] dark:fill-[#9085e9]" };
const CALLS = { stroke: "stroke-[#1baf7a] dark:stroke-[#199e70]", fill: "fill-[#1baf7a] dark:fill-[#199e70]" };
const BUDGET_FILL: Record<BudgetState, string> = {
  good: "bg-[#0ca30c]",
  warning: "bg-[#fab219]",
  critical: "bg-[#d03b3b]",
};
const BUDGET_TEXT: Record<BudgetState, string> = {
  good: "Within budget",
  warning: "Past the first alert",
  critical: "Past the last alert",
};
const CACHE_LABELS: Record<AppCacheKind, string> = {
  answer: "Repeated answers",
  guard: "Safety checks",
  rewrite: "Query rewrites",
  embedding: "Search embeddings",
};

const pct1 = (v: number | null): string => (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
const LABEL = "truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-neutral-500";

/** One metric card: label (with optional explanation or action), headline figure, chart. */
function Cell({ label, info, action, value, children }: {
  label: string;
  info?: string;
  action?: ReactNode;
  value?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section aria-label={label} className={`${CARD} flex min-w-0 flex-col gap-2 p-4`}>
      <header className="flex items-center justify-between gap-2">
        <h3 className={LABEL}>{label}</h3>
        <div className="flex shrink-0 items-center gap-1.5">
          {action}
          {info && (
            <span
              title={info}
              aria-label={info}
              className="flex size-[18px] cursor-help items-center justify-center rounded-full border border-neutral-400 text-[11px] font-semibold text-neutral-500 dark:border-neutral-500 dark:text-neutral-400"
            >
              i
            </span>
          )}
        </div>
      </header>
      {value !== undefined && (
        <p className="text-[28px] font-semibold leading-none tracking-tight tabular-nums text-neutral-900 dark:text-neutral-50">{value}</p>
      )}
      {children}
    </section>
  );
}

/** Inline editor for the organisation's monthly LLM budget (admin action, audited). */
function BudgetEditor({ api, current, onSaved }: { api: ApiClient; current: number; onSaved: () => void }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(String(current));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(): Promise<void> {
    const amount = Number(value);
    if (!Number.isFinite(amount) || amount <= 0 || amount > 1_000_000) {
      setError("Enter an amount between $0.01 and $1,000,000.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.setMonthlyBudget(amount);
      setEditing(false);
      onSaved();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not save the budget.");
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => {
          setValue(String(current));
          setEditing(true);
        }}
        aria-label="Edit monthly budget"
        title="Edit monthly budget"
        className="rounded p-0.5 text-neutral-500 hover:bg-black/[0.05] hover:text-neutral-800 dark:hover:bg-white/[0.08] dark:hover:text-neutral-100"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
          <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z" strokeLinejoin="round" />
        </svg>
      </button>
    );
  }
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      className="absolute inset-x-4 top-11 z-10 rounded-lg border border-black/10 bg-white p-3 shadow-lg dark:border-white/10 dark:bg-[#262624]"
    >
      <label className="text-[11px] font-medium text-neutral-600 dark:text-neutral-300" htmlFor="monthly-budget">
        Monthly LLM budget (USD)
      </label>
      <input
        id="monthly-budget"
        type="number"
        min="0.01"
        step="0.01"
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
        className="mt-1 w-full rounded-md border border-black/15 bg-transparent px-2 py-1 text-sm tabular-nums outline-none focus:border-[#2a78d6] dark:border-white/15"
      />
      {error && <p className="mt-1 text-[11px] text-red-600 dark:text-red-400">{error}</p>}
      <div className="mt-2 flex justify-end gap-2">
        <button type="button" onClick={() => setEditing(false)} className="rounded px-2 py-1 text-xs text-neutral-600 hover:bg-black/[0.04] dark:text-neutral-300 dark:hover:bg-white/[0.06]">
          Cancel
        </button>
        <button type="submit" disabled={saving} className="rounded bg-[#2a78d6] px-2.5 py-1 text-xs font-semibold text-white hover:bg-[#1f68c0] disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </form>
  );
}

function SpendCell({ d, api, onBudgetChanged }: { d: AdminOverview; api: ApiClient; onBudgetChanged: () => void }) {
  const m = d.month;
  const state = budgetState(m.used_fraction, m.alerts);
  const month = new Date(`${m.month_start}T00:00:00Z`).toLocaleDateString("en-GB", { month: "long", timeZone: "UTC" });
  const width = Math.min(100, (m.used_fraction ?? 0) * 100);
  const alerts = m.alerts.map((a) => `${Math.round(a * 100)}%`).join(" and ");
  return (
    <div className="relative">
      <Cell
        label={`${month} spend`}
        info={`LLM spend this calendar month (UTC) against the organisation's monthly budget. Alert marks at ${alerts}.`}
        action={<BudgetEditor api={api} current={m.budget_usd} onSaved={onBudgetChanged} />}
      >
        <div className="mt-1 flex items-baseline justify-between gap-2 text-sm">
          <span className="font-medium text-neutral-800 dark:text-neutral-200">Organisation</span>
          <span className="tabular-nums text-neutral-800 dark:text-neutral-200">
            {money(m.spend_usd)} / {money(m.budget_usd)}
          </span>
        </div>
        <div
          role="meter"
          aria-label={`${month} spend against budget`}
          aria-valuemin={0}
          aria-valuemax={m.budget_usd}
          aria-valuenow={m.spend_usd}
          aria-valuetext={`${money(m.spend_usd)} of ${money(m.budget_usd)}, ${BUDGET_TEXT[state].toLowerCase()}`}
          className="relative mt-2 h-5 overflow-hidden rounded-md bg-neutral-200 dark:bg-neutral-800"
        >
          <div className={`h-full rounded-md ${BUDGET_FILL[state]}`} style={{ width: `${Math.max(width, width > 0 ? 2 : 0)}%` }} />
          {m.alerts.map((a) => (
            <span
              key={a}
              title={`Alert at ${Math.round(a * 100)}% (${money(a * m.budget_usd)})`}
              className="absolute top-1/2 h-3 w-0.5 -translate-y-1/2 rounded bg-neutral-500 dark:bg-neutral-300"
              style={{ left: `${a * 100}%` }}
            />
          ))}
        </div>
        <p className="mt-1 text-[11px] text-neutral-500">
          {BUDGET_TEXT[state]} · {m.used_fraction === null ? "no budget set" : `${(m.used_fraction * 100).toFixed(1)}% used`}
        </p>
      </Cell>
    </div>
  );
}

function CachingCell({ d, labels }: { d: AdminOverview; labels: readonly string[] }) {
  const c = d.caching;
  const breakdown = (Object.keys(CACHE_LABELS) as AppCacheKind[])
    .map((k) => `${CACHE_LABELS[k]}: ${count(c.by_kind[k].hits)} of ${count(c.by_kind[k].lookups)}`)
    .join(" · ");
  return (
    <Cell
      label="Caching: Hit rate"
      info={`Share of cacheable steps EagleEye served from its own cache instead of calling the model again: repeated company-document answers, safety checks, query rewrites and search embeddings (entries kept 24 hours). ${breakdown}.`}
      value={pct1(c.hit_rate)}
    >
      <GlanceLines
        ariaLabel="Cache hit rate over the period"
        labels={labels}
        format={pct1}
        series={[{ name: "Hit rate", values: ratios(d.series.map((s) => s.cache_hits), d.series.map((s) => s.cache_lookups)), ...CACHE }]}
      />
      <p className="text-[11px] text-neutral-500">
        {count(c.hits)} of {count(c.lookups)} lookups · about {money(c.saved_usd, c.saved_usd < 1 ? 4 : 2)} of LLM cost saved
      </p>
    </Cell>
  );
}

/**
 * Usage at a glance (metric content and chart styles after the OpenAI platform dashboard), as
 * six cards matching the rest of the console: tokens, responses, cache hit rate, monthly spend
 * against the admin-set budget, budget remaining and model calls.
 */
export function UsageGlance({ d, hourly, api, onBudgetChanged }: {
  d: AdminOverview;
  hourly: boolean;
  api: ApiClient;
  onBudgetChanged: () => void;
}) {
  const labels = d.series.map((s) => bucketLabel(s.bucket, hourly));
  const cur = d.current;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <Cell label="Total tokens" value={count(cur.tokens_in + cur.tokens_out)}>
        <GlanceLines
          ariaLabel="Input and output tokens over the period"
          labels={labels}
          format={(v) => count(v)}
          series={[
            { name: "Input", values: d.series.map((s) => s.tokens_in), ...INPUT },
            { name: "Output", values: d.series.map((s) => s.tokens_out), ...OUTPUT },
          ]}
        />
        <p className="flex gap-3 text-[11px] text-neutral-500">
          <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-[#eb6834] dark:bg-[#d95926]" />Input {count(cur.tokens_in)}</span>
          <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-[#e87ba4] dark:bg-[#d55181]" />Output {count(cur.tokens_out)}</span>
        </p>
      </Cell>
      <Cell label="Responses and Chat Completions" value={count(cur.requests)}>
        <GlanceBars
          ariaLabel="Responses per period"
          labels={labels}
          values={d.series.map((s) => s.requests)}
          format={(v) => `${count(v)} responses`}
        />
      </Cell>
      <CachingCell d={d} labels={labels} />
      <SpendCell d={d} api={api} onBudgetChanged={onBudgetChanged} />
      <Cell label="Budget remaining" value={money(d.month.remaining_usd)}>
        <p className="text-[11px] text-neutral-500">
          Left of this month&apos;s {money(d.month.budget_usd)} LLM budget · change it with the pencil on the spend card
        </p>
      </Cell>
      <Cell label="Model calls" value={count(cur.llm_calls)}>
        <GlanceLines
          ariaLabel="Model calls over the period"
          labels={labels}
          format={(v) => count(v)}
          series={[{ name: "Calls", values: d.series.map((s) => s.llm_calls), ...CALLS }]}
        />
      </Cell>
    </div>
  );
}
