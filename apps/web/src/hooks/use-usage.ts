"use client";

import { useEffect, useState } from "react";

import type { ApiClient, UsageSummary } from "@/lib/api";

export interface UsageState {
  usage: UsageSummary | null;
  error: string | null;
}

/** Loads usage on mount and again whenever `refreshKey` changes (e.g. after each run). */
export function useUsage(api: ApiClient, refreshKey: number): UsageState {
  const [state, setState] = useState<UsageState>({ usage: null, error: null });

  useEffect(() => {
    let cancelled = false;
    api
      .getUsage()
      .then((usage) => !cancelled && setState({ usage, error: null }))
      .catch((e: unknown) => {
        if (!cancelled) {
          setState((prev) => ({ ...prev, error: e instanceof Error ? e.message : "Usage unavailable" }));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [api, refreshKey]);

  return state;
}
