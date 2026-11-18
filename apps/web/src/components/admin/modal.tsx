"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { useBackCloses } from "@/hooks/use-back-closes";

/** Native modal <dialog>: focus stays inside, Esc closes (unless `busy`), page behind is inert. */
export function Modal({ open, title, subtitle, busy = false, onClose, children, wide = false, size }: {
  open: boolean;
  title: string;
  subtitle?: string;
  busy?: boolean;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  size?: "xl"; // document viewer
}) {
  const width =
    size === "xl"
      ? "w-[min(64rem,calc(100vw-2rem))]"
      : wide
        ? "w-[min(40rem,calc(100vw-2rem))]"
        : "w-[min(28rem,calc(100vw-2rem))]";
  const ref = useRef<HTMLDialogElement>(null);
  const close = useBackCloses(open, onClose); // phones: Back closes the dialog
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby="modal-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
      // m-auto: Tailwind's reset removes the margin the browser uses to centre a modal dialog
      className={`max-md:pt-safe max-md:pb-safe m-auto ${width} max-md:m-0 max-md:h-dvh max-md:max-h-none max-md:w-full max-md:max-w-none max-md:rounded-none rounded-xl border border-black/10 bg-white p-0 text-neutral-900 shadow-2xl backdrop:bg-black/50 dark:border-white/10 dark:bg-[#1a1a19] dark:text-neutral-100`}
    >
      {open && (
        <div className={`flex flex-col max-md:h-full max-md:max-h-full ${size === "xl" ? "max-h-[90dvh]" : "max-h-[85dvh]"}`}>
          <header className="flex items-start justify-between gap-3 border-b border-black/[0.06] px-5 py-4 dark:border-white/10">
            <div>
              <h2 id="modal-title" className="text-sm font-semibold">{title}</h2>
              {subtitle && <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>}
            </div>
            <button
              type="button"
              onClick={close}
              disabled={busy}
              aria-label="Close"
              className="-m-1.5 flex h-9 w-9 shrink-0 items-center justify-center rounded text-lg leading-none text-neutral-400 hover:text-neutral-700 disabled:opacity-40 dark:hover:text-neutral-200"
            >
              ×
            </button>
          </header>
          <div className="min-h-0 overflow-y-auto px-5 py-4">{children}</div>
        </div>
      )}
    </dialog>
  );
}

export const FIELD =
  "w-full rounded-md border border-black/15 bg-transparent px-2.5 py-1.5 text-sm outline-none focus:border-[#2a78d6] focus:ring-2 focus:ring-[#2a78d6]/20 dark:border-white/15";
export const PRIMARY_BUTTON =
  "rounded-md bg-[#2a78d6] px-3 py-1.5 text-xs font-semibold text-white hover:bg-[#1f68c0] disabled:cursor-not-allowed disabled:opacity-50";
export const SECONDARY_BUTTON =
  "rounded-md border border-black/15 px-3 py-1.5 text-xs hover:bg-black/[0.04] disabled:opacity-50 dark:border-white/15 dark:hover:bg-white/[0.06]";
