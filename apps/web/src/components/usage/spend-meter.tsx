"use client";

import { money, percent, quotaSeverity, type Severity } from "@/lib/format";

const FILL: Record<Severity, string> = {
  normal: "var(--viz-accent)",
  warning: "var(--status-warning)",
  critical: "var(--status-critical)",
};

const MIN_VISIBLE_PX = 4; // any spend at all shows a nub, so the meter reads as live

interface SpendMeterProps {
  costUsd: number;
  limitUsd: number;
}

/** Meter: fill carries severity; the track is a lighter step of the same blue ramp. */
export function SpendMeter({ costUsd, limitUsd }: SpendMeterProps) {
  const fraction = limitUsd > 0 ? costUsd / limitUsd : 0;
  const clamped = Math.min(fraction, 1);
  const severity = quotaSeverity(fraction);
  const remaining = Math.max(limitUsd - costUsd, 0);

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-lg font-semibold tabular-nums text-neutral-900 dark:text-neutral-100">
          {money(costUsd)}
        </span>
        <span className="text-[11px] text-neutral-500 dark:text-neutral-400">
          of {money(limitUsd)} limit
        </span>
      </div>
      <div
        role="meter"
        aria-label="Spend against usage limit"
        aria-valuemin={0}
        aria-valuemax={limitUsd}
        aria-valuenow={Number(costUsd.toFixed(4))}
        aria-valuetext={`${money(costUsd)} of ${money(limitUsd)} (${percent(fraction)})`}
        className="mt-1.5 h-2 w-full overflow-hidden rounded-full"
        style={{ background: "var(--viz-track)" }}
      >
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{
            width: costUsd > 0 ? `max(${MIN_VISIBLE_PX}px, ${clamped * 100}%)` : "0",
            background: FILL[severity],
          }}
        />
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-neutral-500 dark:text-neutral-400">
        <span>
          {severity !== "normal" && (
            <span aria-hidden className="mr-1">
              {severity === "critical" ? "⛔" : "⚠"}
            </span>
          )}
          {percent(fraction)} used
          {severity === "critical" && " · limit almost reached"}
        </span>
        <span className="tabular-nums">{money(remaining)} left</span>
      </div>
    </div>
  );
}
