"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

export type Loadable<T> =
  | { kind: "loading" }
  | { kind: "ok"; data: T; at: Date }
  | { kind: "forbidden" }
  | { kind: "error"; message: string };

/**
 * Loads one console section; `deps` changes reload it. `refreshMs` polls (System tab).
 * A 403 becomes "forbidden" so the page can show "Not authorised" instead of an error.
 */
export function useAdminData<T>(
  load: () => Promise<T>,
  deps: readonly unknown[],
  refreshMs?: number,
): [Loadable<T>, () => void] {
  const [state, setState] = useState<Loadable<T>>({ kind: "loading" });
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(() => {
    loadRef
      .current()
      .then((data) => setState({ kind: "ok", data, at: new Date() }))
      .catch((e: unknown) => {
        if (e instanceof ApiError && e.status === 403) setState({ kind: "forbidden" });
        else setState({ kind: "error", message: e instanceof Error ? e.message : "Failed to load" });
      });
  }, []);

  useEffect(() => {
    setState({ kind: "loading" });
    reload();
    if (!refreshMs) return;
    const timer = setInterval(reload, refreshMs);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- deps are the caller's reload keys
  }, [reload, refreshMs, ...deps]);

  return [state, reload];
}
