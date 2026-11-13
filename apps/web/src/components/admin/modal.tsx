"use client";

import { useEffect, useRef, type ReactNode } from "react";

/** Native modal <dialog>: focus stays inside, Esc closes (unless `busy`), page behind is inert. */
export function Modal({ open, title, subtitle, busy = false, onClose, children, wide = false }: {
  open: boolean;
  title: string;
  subtitle?: string;
  busy?: boolean;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
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
        if (!busy) onClose();
      }}
      // m-auto: Tailwind's reset removes the margin the browser uses to centre a modal dialog
      className={`m-auto ${wide ? "w-[min(40rem,calc(100vw-2rem))]" : "w-[min(28rem,calc(100vw-2rem))]"} rounded-xl border border-black/10 bg-white p-0 text-neutral-900 shadow-2xl backdrop:bg-black/50 dark:border-white/10 dark:bg-[#1a1a19] dark:text-neutral-100`}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-start justify-between gap-3 border-b border-black/[0.06] px-5 py-4 dark:border-white/10">
            <div>
              <h2 id="modal-title" className="text-sm font-semibold">{title}</h2>
              {subtitle && <p className="mt-0.5 text-xs text-neutral-500">{subtitle}</p>}
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              aria-label="Close"
              className="rounded px-1.5 text-lg leading-none text-neutral-400 hover:text-neutral-700 disabled:opacity-40 dark:hover:text-neutral-200"
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
