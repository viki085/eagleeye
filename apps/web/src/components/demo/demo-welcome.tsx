"use client";

import { useEffect } from "react";

import { Icon } from "@/components/admin/icons";
import { gateMessage } from "@/lib/demo-gate";
import { timeLeftLabel, type DemoVisit } from "@/lib/demo-visit";
import { DEMO_GROUPS } from "@/lib/demo-questions";

const LOW_TIME_S = 5 * 60;
const AUTO_SIGN_OUT_MS = 20_000;

/** A thin strip above the chat, demo visits only: privacy note and the time left. */
export function DemoBanner({ visit }: { visit: DemoVisit | null }) {
  const low = visit !== null && visit.seconds_left <= LOW_TIME_S;
  return (
    <div
      role="note"
      className="flex items-center justify-center gap-x-3 gap-y-1 border-b border-[rgba(197,163,104,0.3)] bg-[#9E8253]/[0.07] px-3 py-1.5 text-xs md:flex-wrap md:px-4 md:py-2 text-[#6b5636] dark:text-[#d6bd8f]"
    >
      <span className="font-semibold uppercase tracking-[0.12em] text-[#7d6540] dark:text-[#C5A368]">Demo</span>
      <span className="hidden md:inline">
        Your chats and uploads are private to this visit and deleted after 24 hours. Don&apos;t upload confidential files.
      </span>
      <span className="min-w-0 truncate md:hidden">Private to your visit · deleted after 24 h</span>
      {visit && (
        <span
          aria-live="polite"
          className={`shrink-0 rounded-full px-2 py-0.5 font-semibold tabular-nums ${
            low ? "bg-[#d03b3b]/10 text-[#b42f2f] dark:text-[#e66767]" : "bg-[#9E8253]/[0.12] text-[#7d6540] dark:text-[#C5A368]"
          }`}
        >
          {timeLeftLabel(visit.seconds_left)}
        </span>
      )}
    </div>
  );
}

/** Shown when the visit is over (time, budget or the demo's daily limit): why, and when to return. */
export function DemoEnded({ visit, onSignOut }: { visit: DemoVisit; onSignOut: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onSignOut, AUTO_SIGN_OUT_MS);
    return () => clearTimeout(timer);
  }, [onSignOut]);
  return (
    <div role="alertdialog" aria-modal="true" aria-labelledby="demo-ended" className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
      <div className="w-full max-w-sm rounded-2xl border border-[rgba(197,163,104,0.35)] bg-white p-6 text-center shadow-xl dark:border-[rgba(197,163,104,0.25)] dark:bg-[#141517]">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#7d6540] dark:text-[#C5A368]">Demo</p>
        <h2 id="demo-ended" className="mt-2 text-lg font-semibold text-neutral-900 dark:text-neutral-50">Thanks for trying EagleEye</h2>
        <p className="mt-2 text-sm text-neutral-600 dark:text-neutral-300">{gateMessage({ allowed: false, reason: visit.exhausted, availableAt: visit.available_at })}</p>
        <button
          type="button"
          onClick={onSignOut}
          className="mt-5 w-full rounded-lg bg-[#9E8253] px-3 py-2.5 text-sm font-semibold text-white hover:bg-[#B0925E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#9E8253]/25"
        >
          Sign out
        </button>
      </div>
    </div>
  );
}

/** The empty-chat screen for the demo account: what to try, one click to fill the box. */
export function DemoQuestions({ onPick }: { onPick: (text: string) => void }) {
  return (
    <section aria-labelledby="demo-try" className="mt-2 md:mt-6">
      <div className="text-center">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#7d6540] dark:text-[#C5A368]">
          Welcome to the EagleEye demo
        </p>
        <h2 id="demo-try" className="mt-2 text-xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">
          Try one of these questions
        </h2>
        <p className="mx-auto mt-1.5 max-w-xl text-sm text-neutral-500">
          Grand Line Shipping is a fictional company. Its policies, reports and operations database are
          already loaded, and five data files are in <span className="font-medium">My data files</span>
          <span className="hidden md:inline"> on the right</span>
          <span className="md:hidden"> (the documents button at the top)</span>. Pick a question to put it in
          the message box, then send it.
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
                    className="w-full rounded-lg px-2 py-1.5 text-left outline-none pointer-coarse:py-2.5 transition hover:bg-[#9E8253]/[0.08] focus-visible:ring-2 focus-visible:ring-[#9E8253]/50 dark:hover:bg-[#C5A368]/[0.07]"
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
