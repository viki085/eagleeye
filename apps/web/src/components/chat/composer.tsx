"use client";

import { useLayoutEffect, useRef, useState } from "react";

const MAX_HEIGHT_PX = 320; // beyond this the box scrolls

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
  running?: boolean;
  onStop?: () => void;
  contextNote?: string | null;
}

export function Composer({ disabled, onSend, running = false, onStop, contextNote = null }: ComposerProps) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);

  // grow with the content (new lines and long wrapped lines), up to MAX_HEIGHT_PX
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT_PX)}px`;
    el.style.overflowY = el.scrollHeight > MAX_HEIGHT_PX ? "auto" : "hidden";
  }, [text]);

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
          ref={box}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Message EagleEye…"
          aria-label="Message"
          className="max-h-80 flex-1 resize-none rounded-xl border border-neutral-300 bg-white px-4 py-2.5 text-sm outline-none focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-900"
        />
        {running && onStop ? (
          <button
            onClick={onStop}
            aria-label="Stop answering"
            className="rounded-xl border border-neutral-300 px-4 py-2.5 text-sm font-medium hover:bg-neutral-100 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            ■ Stop
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={disabled || text.trim().length === 0}
            className="rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40"
          >
            Send
          </button>
        )}
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-neutral-400">
        {contextNote !== null && <span className="font-medium text-blue-600">{contextNote} · </span>}
        Enter to send · Shift+Enter for a new line
      </p>
    </div>
  );
}
