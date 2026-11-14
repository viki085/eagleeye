"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { clampSplit } from "@/lib/doc-search";

const STEP = 0.05; // keyboard resize step

/**
 * Two sections stacked vertically with a draggable divider between them. The split is
 * remembered per browser under `storageKey`. Mouse, touch and pen drag the divider; with the
 * divider focused, the arrow keys resize too (and Home resets to an even split).
 */
export function ResizableSplit({ storageKey, top, bottom }: {
  storageKey: string;
  top: ReactNode;
  bottom: ReactNode;
}) {
  const key = `eagleeye-split-${storageKey}`;
  const container = useRef<HTMLDivElement>(null);
  const [fraction, setFraction] = useState(0.5);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    try {
      const saved = Number(localStorage.getItem(key));
      if (saved > 0) setFraction(clampSplit(saved));
    } catch {
      // storage blocked: keep the even split
    }
  }, [key]);

  const commit = useCallback(
    (next: number) => {
      const value = clampSplit(next);
      setFraction(value);
      try {
        localStorage.setItem(key, String(value));
      } catch {
        // storage blocked: the size still applies for this page view
      }
    },
    [key],
  );

  function onPointerDown(e: React.PointerEvent<HTMLDivElement>): void {
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
  }

  function onPointerMove(e: React.PointerEvent<HTMLDivElement>): void {
    if (!dragging || !container.current) return;
    const box = container.current.getBoundingClientRect();
    if (box.height > 0) setFraction(clampSplit((e.clientY - box.top) / box.height));
  }

  function onPointerUp(e: React.PointerEvent<HTMLDivElement>): void {
    if (!dragging) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    setDragging(false);
    commit(fraction);
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>): void {
    const moves: Record<string, number> = { ArrowUp: -STEP, ArrowDown: STEP };
    if (e.key in moves) {
      e.preventDefault();
      commit(fraction + moves[e.key]);
    } else if (e.key === "Home") {
      e.preventDefault();
      commit(0.5);
    }
  }

  return (
    <div ref={container} className={`flex min-h-0 flex-1 flex-col ${dragging ? "select-none" : ""}`}>
      <div className="flex min-h-0 flex-col" style={{ flex: `${fraction} 1 0` }}>
        {top}
      </div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize sections"
        aria-valuemin={15}
        aria-valuemax={85}
        aria-valuenow={Math.round(fraction * 100)}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={() => commit(0.5)}
        onKeyDown={onKeyDown}
        title="Drag to resize · double-click to reset"
        className="group relative h-2 shrink-0 cursor-row-resize touch-none outline-none"
      >
        <div
          className={`absolute inset-x-0 top-1/2 h-px -translate-y-1/2 transition-all ${
            dragging
              ? "h-0.5 bg-blue-500"
              : "bg-neutral-200 group-hover:h-0.5 group-hover:bg-blue-400 group-focus-visible:h-0.5 group-focus-visible:bg-blue-500 dark:bg-neutral-800"
          }`}
        />
      </div>
      <div className="flex min-h-0 flex-col" style={{ flex: `${1 - fraction} 1 0` }}>
        {bottom}
      </div>
    </div>
  );
}
