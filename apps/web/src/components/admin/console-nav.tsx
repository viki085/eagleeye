"use client";

import { Icon, type IconName } from "@/components/admin/icons";

export const SECTIONS = [
  { id: "overview", label: "Overview", icon: "overview", ranged: true,
    description: "Platform adoption, reliability, spend and live health at a glance." },
  { id: "users", label: "Users", icon: "users", ranged: true,
    description: "Accounts, activity and spend per user. Chat content is never shown." },
  { id: "usage", label: "Usage & cost", icon: "usage", ranged: true,
    description: "Billed LLM spend by model and day, top spenders and agent tool usage." },
  { id: "safety", label: "Quality & safety", icon: "safety", ranged: true,
    description: "Guardrail events, SQL refusals, sandbox results, failures and the admin audit trail." },
  { id: "content", label: "Content", icon: "content", ranged: false,
    description: "The enterprise knowledge base and indexing status for documents and data files." },
  { id: "system", label: "System & controls", icon: "system", ranged: false,
    description: "Service health, queues and kill switches. Refreshes every 30 seconds." },
] as const satisfies readonly { id: string; label: string; icon: IconName; ranged: boolean; description: string }[];

export type SectionId = (typeof SECTIONS)[number]["id"];

/** Vertical report navigation on wide screens, a scrollable strip on narrow ones. */
export function ConsoleNav({ active, onSelect }: { active: SectionId; onSelect: (id: SectionId) => void }) {
  return (
    <nav
      aria-label="Console sections"
      className="shrink-0 border-b border-black/[0.08] bg-white dark:border-white/10 dark:bg-[#1a1a19] lg:w-56 lg:border-b-0 lg:border-r"
    >
      <p className="hidden px-4 pb-2 pt-4 text-[10px] font-semibold uppercase tracking-[0.1em] text-neutral-400 lg:block">
        Reports
      </p>
      <div role="tablist" aria-orientation="vertical" className="flex gap-1 overflow-x-auto px-2 py-2 [scrollbar-width:none] lg:flex-col lg:overflow-visible lg:py-0 [&::-webkit-scrollbar]:hidden">
        {SECTIONS.map((s) => {
          const selected = s.id === active;
          return (
            <button
              key={s.id}
              type="button"
              role="tab"
              aria-selected={selected}
              onClick={(e) => {
                onSelect(s.id);
                // phones: the strip scrolls sideways; keep the chosen section in view
                e.currentTarget.scrollIntoView({ block: "nearest", inline: "nearest" });
              }}
              className={`relative flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-left text-[13px] transition-colors ${
                selected
                  ? "bg-[#2a78d6]/10 font-semibold text-[#1d5fae] dark:bg-[#3987e5]/15 dark:text-[#8ab8f0]"
                  : "text-neutral-600 hover:bg-black/[0.04] hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-white/[0.05] dark:hover:text-neutral-100"
              }`}
            >
              {selected && <span aria-hidden="true" className="absolute inset-y-1.5 left-0 hidden w-[3px] rounded-r bg-[#2a78d6] lg:block" />}
              <Icon name={s.icon} className="h-4 w-4 shrink-0" />
              {s.label}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
