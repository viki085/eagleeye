"use client";

import { useEffect, useRef, useState } from "react";

import { DELETE_WORD, isDeleteConfirmed } from "@/lib/admin-library";

interface ConfirmDeleteDialogProps {
  /** What is being deleted; null keeps the dialog closed. */
  names: readonly string[] | null;
  /** One line on the consequence, e.g. "They disappear from everyone's answers." */
  consequence: string;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}

/**
 * Destructive-action confirmation in the AWS style: the Delete button stays disabled until the
 * admin types "delete". A native modal <dialog>: focus stays inside, Esc cancels.
 */
export function ConfirmDeleteDialog({ names, consequence, onConfirm, onClose }: ConfirmDeleteDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const open = names !== null && names.length > 0;

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setText("");
      setError(null);
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const confirmed = isDeleteConfirmed(text);
  const count = names?.length ?? 0;
  const heading = count === 1 ? `Delete "${names?.[0]}"?` : `Delete ${count} documents?`;

  async function submit(): Promise<void> {
    if (!confirmed || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not delete. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-delete-title"
      onCancel={(e) => {
        e.preventDefault(); // Esc: close through state so parent and dialog stay in step
        if (!busy) onClose();
      }}
      // m-auto: Tailwind's reset zeroes the margin the browser uses to centre a modal dialog
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg border border-neutral-200 bg-white p-0 text-neutral-900 shadow-xl backdrop:bg-black/50 dark:border-neutral-800 dark:bg-neutral-950 dark:text-neutral-100"
    >
      {open && (
        <form
          method="dialog"
          className="flex flex-col gap-3 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <h2 id="confirm-delete-title" className="text-sm font-semibold [text-wrap:balance]">
            {heading}
          </h2>
          {count > 1 && (
            <ul className="max-h-32 overflow-y-auto rounded border border-neutral-200 px-3 py-1.5 text-xs dark:border-neutral-800">
              {names?.map((n) => (
                <li key={n} className="truncate py-0.5">{n}</li>
              ))}
            </ul>
          )}
          <p className="text-xs text-neutral-600 dark:text-neutral-400">
            {consequence} This can&apos;t be undone.
          </p>
          <label className="flex flex-col gap-1 text-xs">
            <span>
              To confirm, type <strong className="font-mono">{DELETE_WORD}</strong> in the box below.
            </span>
            <input
              autoFocus
              value={text}
              onChange={(e) => setText(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              placeholder={DELETE_WORD}
              aria-describedby={error ? "confirm-delete-error" : undefined}
              className="rounded border border-neutral-300 bg-transparent px-2 py-1.5 font-mono text-sm outline-none focus:border-red-500 dark:border-neutral-700"
            />
          </label>
          {error && (
            <p id="confirm-delete-error" role="alert" className="text-xs text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded border border-neutral-300 px-3 py-1.5 text-xs hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-900"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!confirmed || busy}
              className="rounded bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? "Deleting…" : "Delete"}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
