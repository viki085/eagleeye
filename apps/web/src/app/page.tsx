"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchHealth, type HealthData } from "@/lib/api";
import { ServiceCard } from "@/components/service-card";

const POLL_MS = 5000;

type ConnState =
  | { kind: "loading" }
  | { kind: "ok"; health: HealthData; at: Date }
  | { kind: "api-down"; message: string };

export default function StatusPage() {
  const [state, setState] = useState<ConnState>({ kind: "loading" });

  const poll = useCallback(async (signal?: AbortSignal) => {
    try {
      const health = await fetchHealth(signal);
      setState({ kind: "ok", health, at: new Date() });
    } catch (error: unknown) {
      if (error instanceof DOMException && error.name === "AbortError") return;
      const message = error instanceof Error ? error.message : "Unexpected error";
      setState({ kind: "api-down", message });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void poll(controller.signal);
    const timer = setInterval(() => void poll(controller.signal), POLL_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [poll]);

  return (
    <main className="mx-auto min-h-screen max-w-3xl px-4 py-12">
      <header className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight">EagleEye</h1>
        <p className="mt-1 text-sm text-neutral-500">
          Phase 0 — platform status
        </p>
      </header>

      <OverallBanner state={state} />

      {state.kind === "ok" && (
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {state.health.services.map((svc) => (
            <ServiceCard key={svc.name} service={svc} />
          ))}
        </div>
      )}

      {state.kind === "ok" && (
        <p className="mt-6 text-xs text-neutral-400">
          Last checked {state.at.toLocaleTimeString()} · polling every {POLL_MS / 1000}s
        </p>
      )}
    </main>
  );
}

function OverallBanner({ state }: { state: ConnState }) {
  if (state.kind === "loading") {
    return (
      <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900">
        Connecting to API…
      </div>
    );
  }
  if (state.kind === "api-down") {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950">
        <p className="text-sm font-medium text-red-700 dark:text-red-300">API unreachable</p>
        <p className="mt-1 text-xs text-red-600 dark:text-red-400">{state.message}</p>
      </div>
    );
  }
  const up = state.health.overall === "up";
  return (
    <div
      className={
        up
          ? "rounded-lg border border-emerald-300 bg-emerald-50 p-4 dark:border-emerald-900 dark:bg-emerald-950"
          : "rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-900 dark:bg-amber-950"
      }
    >
      <p
        className={
          up
            ? "text-sm font-medium text-emerald-700 dark:text-emerald-300"
            : "text-sm font-medium text-amber-700 dark:text-amber-300"
        }
      >
        {up ? "All systems operational" : "Degraded — one or more services down"}
      </p>
    </div>
  );
}
