"use client";

import { useCallback, useEffect, useRef } from "react";

const DEPTH_KEY = "eagleeyeOverlayDepth";

function depthOf(state: unknown): number {
  const value = (state as Record<string, unknown> | null)?.[DEPTH_KEY];
  return typeof value === "number" ? value : 0;
}

/**
 * Lets the phone's Back button (or gesture) close a panel or pop-up instead of leaving the
 * page. While it is open, one history entry is added, marked with its depth so that stacked
 * pop-ups (a data file profile over the documents panel) close one at a time. Next's own
 * history state is copied into the entry, so Next treats Back as staying on the same page.
 *
 * Returns `close`: use it for the close buttons, so the added entry is taken off too. If the
 * owner closes the pop-up some other way, the entry is removed when `open` turns false.
 */
export function useBackCloses(open: boolean, onClose: () => void): () => void {
  const depth = useRef(0); // the depth of the entry this pop-up added; 0 = none
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) {
      if (depth.current > 0) {
        depth.current = 0;
        window.history.back();
      }
      return;
    }
    if (depth.current === 0) {
      const state = (window.history.state ?? {}) as Record<string, unknown>;
      const next = depthOf(state) + 1;
      window.history.pushState({ ...state, [DEPTH_KEY]: next }, "");
      depth.current = next;
    }
    const onPop = (e: PopStateEvent) => {
      if (depthOf(e.state) < depth.current) {
        depth.current = 0;
        closeRef.current();
      }
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [open]);

  return useCallback(() => {
    if (depth.current > 0) {
      window.history.back(); // the popstate handler closes it
    } else {
      closeRef.current();
    }
  }, []);
}
