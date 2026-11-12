"use client";

import { useState } from "react";

import type { DailyUsage } from "@/lib/api";
import { compactNumber, dayLabel, money } from "@/lib/format";

const CHART_HEIGHT_PX = 44;
const MIN_BAR_PX = 2; // zero days show a baseline stub so the week's shape stays legible

interface DailyColumnsProps {
  days: readonly DailyUsage[];
}

/** Single-series column chart of daily spend: today in the accent, earlier days a lighter
 *  step of the same ramp. Hover/focus a column to read that day in the header. */
export function DailyColumns({ days }: DailyColumnsProps) {
  const [active, setActive] = useState<number | null>(null);
  const max = Math.max(...days.map((d) => d.cost_usd), 0);
  const weekTotal = days.reduce((sum, d) => sum + d.cost_usd, 0);
  const shown = active !== null ? days[active] : null;
  const lastIndex = days.length - 1;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-medium text-neutral-700 dark:text-neutral-300">
          {shown ? dayLabel(shown.day) : "Last 7 days"}
        </span>
        <span className="text-xs tabular-nums text-neutral-500 dark:text-neutral-400" aria-live="polite">
          {shown ? `${money(shown.cost_usd)} · ${compactNumber(shown.tokens)} tok` : money(weekTotal)}
        </span>
      </div>
      <div
        className="mt-1.5 flex items-end gap-1.5 border-b border-neutral-200 dark:border-neutral-800"
        style={{ height: CHART_HEIGHT_PX }}
        onMouseLeave={() => setActive(null)}
      >
        {days.map((d, i) => {
          const height = max > 0 ? Math.max((d.cost_usd / max) * CHART_HEIGHT_PX, MIN_BAR_PX) : MIN_BAR_PX;
          const isToday = i === lastIndex;
          return (
            <button
              key={d.day}
              type="button"
              aria-label={`${dayLabel(d.day)}: ${money(d.cost_usd)}, ${compactNumber(d.tokens)} tokens`}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="flex h-full flex-1 items-end justify-center outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <span
                className="block w-full max-w-[24px] rounded-t transition-opacity"
                style={{
                  height,
                  background: isToday ? "var(--viz-accent)" : "var(--viz-muted-bar)",
                  opacity: active === null || active === i ? 1 : 0.45,
                }}
              />
            </button>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1.5 text-[10px] text-neutral-400">
        {days.map((d, i) => (
          <span key={d.day} className={`flex-1 text-center ${i === lastIndex ? "font-semibold text-neutral-600 dark:text-neutral-300" : ""}`}>
            {dayLabel(d.day).slice(0, 2)}
          </span>
        ))}
      </div>
    </div>
  );
}
