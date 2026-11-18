"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

import { type Loadable, stateWhileReloading } from "./admin-data-state";

export type { Loadable } from "./admin-data-state";

/**
 * Loads one console section; `deps` changes reload it. `refreshMs` polls (System tab).
 * A 403 becomes "forbidden" so the page can show "Not authorised" instead of an error.
 * A reload keeps the numbers on screen until the new ones arrive, and only the latest
 * request's answer is applied (a slow earlier one can't overwrite a newer one).
 */
export function useAdminData<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
  refreshMs?: number,
): [Loadable<T>, () => void] {
  const [state, setState] = useState<Loadable<T>>({ kind: "loading" });
  const loadRef = useRef(load);
  loadRef.current = load;
  const latest = useRef(0);

  const reload = useCallback(() => {
    const request = ++latest.current;
    loadRef
      .current()
      .then((data) => {
        if (request === latest.current) setState({ kind: "ok", data, at: new Date() });
      })
      .catch((e: unknown) => {
        if (request !== latest.current) return;
        if (e instanceof ApiError && e.status === 403) setState({ kind: "forbidden" });
        else setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
      });
  }, []);

  useEffect(() => {
    setState(stateWhileReloading);
    reload();
    if (!refreshMs) return;
    const timer = setInterval(reload, refreshMs);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the caller's reload keys
  }, [reload, refreshMs, ...deps]);

  return [state, reload];
}
