"use client";

import { useEffect, useState } from "react";

import type { ApiClient } from "@/lib/api";
import type { DemoVisit } from "@/lib/demo-visit";

const HEARTBEAT_MS = 60_000;
const TICK_MS = 1_000;

/**
 * Demo visits only: a heartbeat when the app opens and every minute while it is open (that is
 * how the visit's time is counted; closing the tab pauses it), plus a local countdown between
 * heartbeats. Returns null until the first answer.
 */
export function useDemoVisit(api: ApiClient, enabled: boolean): DemoVisit | null {
  const [visit, setVisit] = useState<DemoVisit | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const beat = () => {
      api
        .demoHeartbeat()
        .then((v) => !cancelled && setVisit(v))
        .catch(() => undefined); // a missed heartbeat only means that minute isn't counted
    };
    beat();
    const heartbeat = setInterval(beat, HEARTBEAT_MS);
    const tick = setInterval(() => {
      setVisit((v) => (v && !v.exhausted ? { ...v, seconds_left: Math.max(v.seconds_left - 1, 0) } : v));
    }, TICK_MS);
    return () => {
      cancelled = true;
      clearInterval(heartbeat);
      clearInterval(tick);
    };
  }, [api, enabled]);

  return visit;
}
