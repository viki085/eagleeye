"use client";

import { Icon } from "@/components/admin/icons";
import type { UsageSummary } from "@/lib/api";
import { DEMO_GROUPS } from "@/lib/demo-questions";

/** A thin strip above the chat, demo account only. */
export function DemoBanner({ usage }: { usage: UsageSummary | null }) {
  const spent = usage ? `$${usage.cost_usd.toFixed(2)} of $${usage.limit_usd.toFixed(2)}` : null;
  return (
    <div
      role="note"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-[rgba(197,163,104,0.3)] bg-[#9E8253]/[0.07] px-4 py-2 text-xs text-[#6b5636] dark:text-[#d6bd8f]"
    >
      <span className="font-semibold uppercase tracking-[0.12em] text-[#7d6540] dark:text-[#C5A368]">Demo</span>
      <span>Shared account: anyone with the demo sign-in can see these chats. Don&apos;t upload private files.</span>
      {spent && <span className="tabular-nums text-neutral-500">AI budget used: {spent}</span>}
    </div>
  );
}

/** The empty-chat screen for the demo account: what to try, one click to fill the box. */
export function DemoQuestions({ onPick }: { onPick: (text: string) => void }) {
  return (
    <section aria-labelledby="demo-try" className="mt-6">
      <div className="text-center">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#7d6540] dark:text-[#C5A368]">
          Welcome to the EagleEye demo
        </p>
        <h2 id="demo-try" className="mt-2 text-xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">
          Try one of these questions
        </h2>
        <p className="mx-auto mt-1.5 max-w-xl text-sm text-neutral-500">
          Grand Line Shipping is a fictional company. Its policies, reports and operations database are
          already loaded, and four data files are in <span className="font-medium">My data files</span> on
          the right. Click a question to put it in the message box, then press Enter.
        </p>
      </div>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {DEMO_GROUPS.map((group) => (
          <div
            key={group.title}
            className="rounded-xl border border-black/[0.08] bg-white p-3 dark:border-white/[0.08] dark:bg-[#141517]"
          >
            <p className="flex items-center gap-2 px-1 pb-2 text-xs font-semibold text-neutral-700 dark:text-neutral-200">
              <span className="grid h-6 w-6 place-items-center rounded-md border border-[rgba(197,163,104,0.25)] bg-[#9E8253]/[0.08] text-[#7d6540] dark:bg-[#1C1B18] dark:text-[#C5A368]">
                <Icon name={group.icon} className="h-3.5 w-3.5" />
              </span>
              {group.title}
            </p>
            <ul className="flex flex-col gap-1">
              {group.questions.map((q) => (
                <li key={q.text}>
                  <button
                    type="button"
                    onClick={() => onPick(q.text)}
                    className="w-full rounded-lg px-2 py-1.5 text-left outline-none transition hover:bg-[#9E8253]/[0.08] focus-visible:ring-2 focus-visible:ring-[#9E8253]/50 dark:hover:bg-[#C5A368]/[0.07]"
                  >
                    <span className="line-clamp-2 text-[13px] leading-snug text-neutral-800 dark:text-neutral-200">
                      {q.text}
                    </span>
                    <span className="mt-0.5 block text-[11px] text-neutral-500">{q.note}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
