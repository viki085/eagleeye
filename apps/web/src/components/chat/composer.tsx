"use client";

import { useState } from "react";

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
}

export function Composer({ disabled, onSend }: ComposerProps) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="border-t border-neutral-200 p-4 dark:border-neutral-800">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={Math.min(6, Math.max(1, text.split("\n").length))}
          placeholder="Message EagleEye…"
          className="flex-1 resize-none rounded-xl border border-neutral-300 bg-white px-4 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
        />
        <button
          onClick={submit}
          disabled={disabled || text.trim().length === 0}
          className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
        >
          Send
        </button>
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-neutral-400">
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
