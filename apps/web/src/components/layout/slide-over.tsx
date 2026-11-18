"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { useBackCloses } from "@/hooks/use-back-closes";

const SWIPE_CLOSE_PX = 60; // a horizontal swipe this far towards the edge closes the panel

type Side = "left" | "right";

interface SlideOverProps {
  open: boolean;
  side: Side;
  label: string;
  onClose: () => void;
  /** Panel width classes; defaults to most of a phone's width. */
  widthClass?: string;
  /** Children get `close`, which also undoes the history entry the panel added. */
  children: (close: () => void) => ReactNode;
}

/** A panel that slides over the page from one edge, with a dimmed backdrop. It closes on a
 * backdrop tap, Escape, the Back button, or a swipe towards its edge. */
export function SlideOver({ open, side, label, onClose, widthClass = "w-[85vw] max-w-sm", children }: SlideOverProps) {
  const close = useBackCloses(open, onClose);
  const panel = useRef<HTMLElement>(null);
  const touchStart = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open) return null;

  const onTouchEnd = (x: number) => {
    if (touchStart.current === null) return;
    const dx = x - touchStart.current;
    touchStart.current = null;
    if ((side === "left" && dx < -SWIPE_CLOSE_PX) || (side === "right" && dx > SWIPE_CLOSE_PX)) close();
  };

  return (
    <div className={`fixed inset-0 z-40 flex ${side === "right" ? "justify-end" : ""}`}>
      <div aria-hidden="true" onClick={close} className="ee-fade-in absolute inset-0 bg-black/40" />
      <section
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
        onTouchStart={(e) => {
          touchStart.current = e.touches[0]?.clientX ?? null;
        }}
        onTouchEnd={(e) => onTouchEnd(e.changedTouches[0]?.clientX ?? 0)}
        className={`${side === "left" ? "ee-slide-from-left" : "ee-slide-from-right"} relative flex h-full ${widthClass} flex-col overflow-hidden bg-neutral-50 shadow-2xl outline-none dark:bg-neutral-900`}
      >
        {children(close)}
      </section>
    </div>
  );
}
