"use client";

import { useState } from "react";

import type { StepView } from "@/lib/run-fold";

const KIND_ICON: Record<string, string> = {
  guard: "🛡",
  llm: "✦",
  tool: "⚙",
  retrieval: "⌕",
  check: "✓",
};

const STATUS_CLASS: Record<StepView["status"], string> = {
  running: "text-amber-600 dark:text-amber-400",
  ok: "text-emerald-600 dark:text-emerald-400",
  error: "text-red-600 dark:text-red-400",
  skipped: "text-neutral-400",
};

function formatMs(ms: number | null): string {
  if (ms === null) return "";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function totalSeconds(steps: readonly StepView[]): string {
  const top = steps.filter((s) => s.parentId === null);
  const ms = top.reduce((sum, s) => sum + (s.durationMs ?? 0), 0);
  return `${(ms / 1000).toFixed(1)} s`;
}

function StepRow({ step, all, depth }: { step: StepView; all: readonly StepView[]; depth: number }) {
  const children = all.filter((s) => s.parentId === step.id);
  return (
    <li>
      <div className="flex min-w-0 items-baseline gap-2 py-0.5" style={{ paddingLeft: `${depth * 16}px` }}>
        <span aria-hidden className="w-4 shrink-0 text-center text-neutral-400">
          {KIND_ICON[step.kind] ?? "•"}
        </span>
        <span className="shrink-0 whitespace-nowrap font-medium text-neutral-700 dark:text-neutral-300">
          {step.name}
        </span>
        {step.inputSummary && step.kind === "tool" && (
          <code className="min-w-0 truncate text-[11px] text-neutral-400" title={step.inputSummary}>
            {step.inputSummary}
          </code>
        )}
        <span
          className={`ml-auto min-w-0 max-w-[55%] truncate ${STATUS_CLASS[step.status]}`}
          title={step.outputSummary}
        >
          {step.status === "running" ? "running…" : step.outputSummary || step.status}
        </span>
        <span className="w-14 shrink-0 text-right tabular-nums text-neutral-400">{formatMs(step.durationMs)}</span>
      </div>
      {children.length > 0 && (
        <ul>
          {children.map((c) => (
            <StepRow key={c.id} step={c} all={all} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

interface StepTreeProps {
  steps: readonly StepView[];
  live?: boolean;
}

export function StepTree({ steps, live = false }: StepTreeProps) {
  const [open, setOpen] = useState<boolean | null>(null);
  if (steps.length === 0) return null;
  const expanded = open ?? live;
  const ids = new Set(steps.map((s) => s.id));
  const roots = steps.filter((s) => s.parentId === null || !ids.has(s.parentId));
  const label = live
    ? `Working… ${steps.length} step${steps.length === 1 ? "" : "s"}`
    : `Worked for ${totalSeconds(steps)} · ${steps.length} steps`;

  return (
    <div className="mb-2 rounded-lg border border-neutral-200 text-xs dark:border-neutral-800">
      <button
        onClick={() => setOpen(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
      >
        <span aria-hidden>{expanded ? "▾" : "▸"}</span>
        <span className={live ? "animate-pulse" : ""}>{label}</span>
      </button>
      {expanded && (
        <ul className="border-t border-neutral-200 px-3 py-1.5 dark:border-neutral-800">
          {roots.map((s) => (
            <StepRow key={s.id} step={s} all={steps} depth={0} />
          ))}
        </ul>
      )}
    </div>
  );
}
