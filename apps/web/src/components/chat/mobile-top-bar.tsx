"use client";

interface MobileTopBarProps {
  title: string;
  busy: boolean;
  /** Documents ticked to restrict answers; shown as a badge on the Documents button. */
  selectedDocs: number;
  onOpenChats: () => void;
  onOpenDocuments: () => void;
  onNewChat: () => void;
}

const ICON_BUTTON =
  "relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-neutral-600 hover:bg-neutral-100 active:bg-neutral-200 disabled:opacity-40 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:active:bg-neutral-700";

function Svg({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d={d} />
    </svg>
  );
}

/** Phone header, as in mobile chat apps: chats menu, the chat's title, documents, new chat. */
export function MobileTopBar({ title, busy, selectedDocs, onOpenChats, onOpenDocuments, onNewChat }: MobileTopBarProps) {
  return (
    <header className="pt-safe shrink-0 border-b border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-950">
      <div className="flex h-12 items-center gap-1 px-1.5">
        <button type="button" onClick={onOpenChats} aria-label="Open chats" className={ICON_BUTTON}>
          <Svg d="M4 7h16M4 12h16M4 17h16" />
        </button>
        <h1 className="min-w-0 flex-1 truncate px-1 text-center text-sm font-semibold">{title}</h1>
        <button
          type="button"
          onClick={onOpenDocuments}
          aria-label={selectedDocs > 0 ? `Documents and data (${selectedDocs} selected)` : "Documents and data"}
          className={ICON_BUTTON}
        >
          <Svg d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5zM14 3v5h5M9 13h6M9 17h6" />
          {selectedDocs > 0 && (
            <span className="absolute right-1 top-1 min-w-4 rounded-full bg-blue-600 px-1 text-center text-[10px] font-semibold leading-4 text-white">
              {selectedDocs}
            </span>
          )}
        </button>
        <button type="button" onClick={onNewChat} disabled={busy} aria-label="New chat" className={ICON_BUTTON}>
          <Svg d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
        </button>
      </div>
    </header>
  );
}
