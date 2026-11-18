"use client";

import { useEffect, useState } from "react";

import { BrandIcon } from "@/components/brand/brand-icon";

const POLL_MS = 5_000;
const GIVE_UP_MS = 6 * 60_000;

interface ServerWakingProps {
  /** true when the API answers its liveness check */
  isUp: () => Promise<boolean>;
}

/** Shown while the first liveness check runs: the app opens only once the server answers. */
export function ServerConnecting() {
  return (
    <main className="grid min-h-dvh place-items-center bg-[#f3f3f0] px-4 dark:bg-[#0b0b0c]">
      <div role="status" aria-live="polite" className="w-full max-w-sm text-center">
        <BrandIcon size={48} className="mx-auto block" />
        <h1 className="mt-5 text-lg font-semibold text-neutral-900 dark:text-neutral-50">Connecting to EagleEye…</h1>
        <div className="mx-auto mt-6 h-1 w-40 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/[0.08]">
          <div className="h-full w-1/3 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full bg-[#9E8253]" />
        </div>
      </div>
    </main>
  );
}

/**
 * The API didn't answer: in the cloud the demo machine sleeps when idle. Ask once for it to be
 * started (/api/wake), check every few seconds, and reload when it's up (usually ~2 minutes).
 */
export function ServerWaking({ isUp }: ServerWakingProps) {
  const [state, setState] = useState<"starting" | "unreachable">("starting");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    void fetch("/api/wake", { method: "POST" })
      .then((r) => r.json())
      .then((d: { state?: string }) => {
        // nothing to wake (a laptop) or the daily run-time cap: say so instead of waiting
        if (!cancelled && (d.state === "not_configured" || d.state === "refused" || d.state === "failed")) {
          setState("unreachable");
        }
      })
      .catch(() => undefined);
    const timer = setInterval(() => {
      void isUp().then((up) => {
        if (cancelled) return;
        if (up) window.location.reload();
        else if (Date.now() - started > GIVE_UP_MS) setState("unreachable");
      });
    }, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [isUp, attempt]);

  return (
    <main className="grid min-h-dvh place-items-center bg-[#f3f3f0] px-4 dark:bg-[#0b0b0c]">
      <div role="status" aria-live="polite" className="w-full max-w-sm text-center">
        <BrandIcon size={48} className="mx-auto block" />
        {state === "starting" ? (
          <>
            <h1 className="mt-5 text-lg font-semibold text-neutral-900 dark:text-neutral-50">Starting EagleEye…</h1>
            <p className="mt-2 text-sm text-neutral-500">
              The server sleeps when nobody is using it. It&apos;s waking up, which usually takes about two minutes. This
              page continues by itself.
            </p>
            <div className="mx-auto mt-6 h-1 w-40 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/[0.08]">
              <div className="h-full w-1/3 animate-[pulse_1.5s_ease-in-out_infinite] rounded-full bg-[#9E8253]" />
            </div>
          </>
        ) : (
          <>
            <h1 className="mt-5 text-lg font-semibold text-neutral-900 dark:text-neutral-50">Can&apos;t reach EagleEye</h1>
            <p className="mt-2 text-sm text-neutral-500">The server isn&apos;t answering right now. Please try again in a few minutes.</p>
            <button
              type="button"
              onClick={() => {
                setState("starting");
                setAttempt((a) => a + 1);
              }}
              className="mt-5 rounded-lg bg-[#9E8253] px-4 py-2 text-sm font-semibold text-white hover:bg-[#B0925E] focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#9E8253]/25"
            >
              Try again
            </button>
          </>
        )}
      </div>
    </main>
  );
}
