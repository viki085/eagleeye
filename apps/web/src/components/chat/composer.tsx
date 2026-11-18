"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { TOUCH_QUERY, useMediaQuery } from "@/hooks/use-media-query";
import { FILE_REF_MIME, insertToken } from "@/lib/file-refs";

const MAX_HEIGHT_PX = 320; // beyond this the box scrolls
const MAX_HEIGHT_TOUCH_PX = 160; // phones: leave room for the answer above the keyboard

interface ComposerProps {
  disabled: boolean;
  onSend: (text: string) => void;
  running?: boolean;
  onStop?: () => void;
  contextNote?: string | null;
  /** Text put into the box from outside (e.g. a suggested question); `id` makes repeats count. */
  draft?: { text: string; id: number } | null;
}

export function Composer({ disabled, onSend, running = false, onStop, contextNote = null, draft = null }: ComposerProps) {
  const [text, setText] = useState("");
  const box = useRef<HTMLTextAreaElement>(null);
  const [dropping, setDropping] = useState(false);
  const pendingCaret = useRef<number | null>(null);
  // touch screens behave like mobile chat apps: Enter is a new line, the button sends
  const touch = useMediaQuery(TOUCH_QUERY);
  const maxHeight = touch ? MAX_HEIGHT_TOUCH_PX : MAX_HEIGHT_PX;

  useEffect(() => {
    if (!draft) return;
    pendingCaret.current = draft.text.length;
    setText(draft.text);
    box.current?.focus();
  }, [draft]);

  const isFileDrag = (e: React.DragEvent) => Array.from(e.dataTransfer.types).includes(FILE_REF_MIME);

  function onDrop(e: React.DragEvent<HTMLTextAreaElement>): void {
    setDropping(false);
    const token = e.dataTransfer.getData(FILE_REF_MIME);
    if (!token) return; // anything else (plain text) keeps the browser's own behaviour
    e.preventDefault();
    const el = e.currentTarget;
    const caret = document.activeElement === el ? el.selectionStart : text.length;
    const next = insertToken(text, caret, token);
    pendingCaret.current = next.caret;
    setText(next.text);
    el.focus();
  }

  // grow with the content (new lines and long wrapped lines), up to MAX_HEIGHT_PX
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
    if (pendingCaret.current !== null) {
      el.setSelectionRange(pendingCaret.current, pendingCaret.current);
      pendingCaret.current = null;
    }
  }, [text, maxHeight]);

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setText("");
  };

  return (
    <div className="pb-safe border-t border-neutral-200 dark:border-neutral-800">
      <div className="px-2 pb-2 pt-2 md:p-4">
      <div className="mx-auto flex max-w-3xl items-end gap-2">
        <textarea
          ref={box}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onDragOver={(e) => {
            if (!isFileDrag(e)) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setDropping(true);
          }}
          onDragLeave={() => setDropping(false)}
          onDrop={onDrop}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !touch && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder="Message EagleEye…"
          aria-label="Message"
          enterKeyHint={touch ? "enter" : "send"}
          // 16px text on phones: iOS zooms the page into any smaller input when it is tapped
          className={`max-h-80 min-w-0 flex-1 resize-none rounded-2xl md:rounded-xl ${dropping ? "ring-2 ring-blue-400 ring-offset-1 dark:ring-offset-neutral-950" : ""} border border-neutral-300 bg-white px-4 py-2.5 text-base outline-none focus:border-blue-500 md:text-sm dark:border-neutral-700 dark:bg-neutral-900`}
        />
        {running && onStop ? (
          <button
            onClick={onStop}
            aria-label="Stop answering"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full border border-neutral-300 text-sm font-medium hover:bg-neutral-100 md:h-auto md:w-auto md:rounded-xl md:px-4 md:py-2.5 dark:border-neutral-700 dark:hover:bg-neutral-800"
          >
            <span aria-hidden="true">■</span>
            <span className="ml-1 hidden md:inline">Stop</span>
          </button>
        ) : (
          <button
            onClick={submit}
            disabled={disabled || text.trim().length === 0}
            aria-label="Send"
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-blue-600 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-40 md:h-auto md:w-auto md:rounded-xl md:px-4 md:py-2.5"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5 md:hidden" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 19V5M5 12l7-7 7 7" />
            </svg>
            <span className="hidden md:inline">Send</span>
          </button>
        )}
      </div>
      {touch ? (
        contextNote !== null && (
          <p className="mx-auto mt-1.5 max-w-3xl text-center text-[11px] font-medium text-blue-600">{contextNote}</p>
        )
      ) : (
        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-neutral-400">
          {contextNote !== null && <span className="font-medium text-blue-600">{contextNote} · </span>}
          Enter to send · Shift+Enter for a new line
        </p>
      )}
      </div>
    </div>
  );
}
