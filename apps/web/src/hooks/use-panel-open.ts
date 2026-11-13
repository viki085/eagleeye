"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Open/collapsed state for a side panel, remembered per browser. Starts open on the server
 * render and reads the stored choice after mount, so hydration never mismatches.
 */
export function usePanelOpen(key: string): [boolean, (open: boolean) => void] {
  const storageKey = `eagleeye-panel-${key}`;
  const [open, setOpenState] = useState(true);

  useEffect(() => {
    try {
      if (localStorage.getItem(storageKey) === "collapsed") setOpenState(false);
    } catch {
      // storage blocked (private mode): stay open
    }
  }, [storageKey]);

  const setOpen = useCallback(
    (next: boolean) => {
      setOpenState(next);
      try {
        localStorage.setItem(storageKey, next ? "open" : "collapsed");
      } catch {
        // storage blocked: the choice still applies for this page view
      }
    },
    [storageKey],
  );

  return [open, setOpen];
}
