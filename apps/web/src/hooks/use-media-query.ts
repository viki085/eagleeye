"use client";

import { useCallback, useSyncExternalStore } from "react";

/** Phone layout: below Tailwind's `md` breakpoint. */
export const PHONE_QUERY = "(max-width: 767px)";
/** Phone or tablet: the documents panel opens over the chat instead of beside it. */
export const COMPACT_QUERY = "(max-width: 1279px)";
/** A touch screen without a precise pointer (phones, most tablets). */
export const TOUCH_QUERY = "(pointer: coarse)";

/**
 * Whether a CSS media query matches, kept current as the window changes size or rotates.
 * The server render (and the first client render) assume it does not match, which is the
 * desktop layout; the real value applies straight after hydration.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia(query);
      list.addEventListener("change", onChange);
      return () => list.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}
