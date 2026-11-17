"use client";

import { useState } from "react";

import { DailyColumns } from "@/components/usage/daily-columns";
import { SpendMeter } from "@/components/usage/spend-meter";
import { TokenSplit } from "@/components/usage/token-split";
import type { UsageState } from "@/hooks/use-usage";

interface UsagePanelProps {
  state: UsageState;
}

export function UsagePanel({ state }: UsagePanelProps) {
  const [open, setOpen] = useState(true);
  const { usage, error } = state;

  return (
    <section
      aria-label="Usage"
      className="border-t border-neutral-200 px-3 pb-3 pt-2 dark:border-neutral-800"
    >
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center justify-between py-1 text-[11px] font-semibold uppercase tracking-wider text-neutral-500 hover:text-neutral-800 dark:text-neutral-400 dark:hover:text-neutral-200"
      >
        <span>Usage</span>
        <span className="font-normal normal-case tracking-normal">
          {usage ? `${usage.runs} answer${usage.runs === 1 ? "" : "s"}` : ""} {open ? "▾" : "▸"}
        </span>
      </button>
      {open && (
        <div className="mt-1 flex flex-col gap-3">
          {usage === null && error === null && (
            <div className="h-24 animate-pulse rounded-lg bg-neutral-200/60 dark:bg-neutral-800/60" />
          )}
          {usage === null && error !== null && (
            <p className="text-[11px] text-neutral-500">Usage unavailable right now.</p>
          )}
          {usage !== null && (
            <>
              {usage.limit_usd !== null && <SpendMeter costUsd={usage.cost_usd} limitUsd={usage.limit_usd} />}
              <TokenSplit tokensIn={usage.tokens_in} tokensOut={usage.tokens_out} />
              <DailyColumns days={usage.daily} />
            </>
          )}
        </div>
      )}
    </section>
  );
}
