"use client";

import { UserButton } from "@clerk/nextjs";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/theme-toggle";
import { usePanelOpen } from "@/hooks/use-panel-open";
import type { ChatSummary } from "@/lib/api";

interface SidebarProps {
  chats: ChatSummary[];
  activeChatId: string | null;
  busy: boolean;
  onNewChat: () => void;
  onSelect: (chatId: string) => void;
  onDelete: (chatId: string) => void;
  footer?: ReactNode;
}

const RAIL_BUTTON =
  "flex h-8 w-8 items-center justify-center rounded-lg text-neutral-500 hover:bg-neutral-200 hover:text-neutral-800 disabled:opacity-50 dark:hover:bg-neutral-800 dark:hover:text-neutral-200";

/** Collapsed: a slim rail that keeps expand, new chat, theme and account one click away. */
function CollapsedRail({ busy, onNewChat, onExpand }: {
  busy: boolean;
  onNewChat: () => void;
  onExpand: () => void;
}) {
  return (
    <aside
      aria-label="Chats (collapsed)"
      className="flex h-full w-12 shrink-0 flex-col items-center gap-2 border-r border-neutral-200 bg-neutral-50 py-3 dark:border-neutral-800 dark:bg-neutral-900"
    >
      <button onClick={onExpand} aria-label="Expand chats panel" title="Expand" className={RAIL_BUTTON}>
        »
      </button>
      <button
        onClick={onNewChat}
        disabled={busy}
        aria-label="New chat"
        title="New chat"
        className={`${RAIL_BUTTON} text-lg`}
      >
        +
      </button>
      <div className="mt-auto flex flex-col items-center gap-2">
        <ThemeToggle />
        <UserButton />
      </div>
    </aside>
  );
}

export function Sidebar({
  chats,
  activeChatId,
  busy,
  onNewChat,
  onSelect,
  onDelete,
  footer,
}: SidebarProps) {
  const [open, setOpen] = usePanelOpen("chats");
  if (!open) {
    return <CollapsedRail busy={busy} onNewChat={onNewChat} onExpand={() => setOpen(true)} />;
  }
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between p-3">
        <span className="text-sm font-semibold tracking-tight">EagleEye</span>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <UserButton />
          <button
            onClick={() => setOpen(false)}
            aria-label="Collapse chats panel"
            title="Collapse"
            className="rounded px-1.5 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
          >
            ‹
          </button>
        </div>
      </div>
      <button
        onClick={onNewChat}
        disabled={busy}
        className="mx-3 mb-2 rounded-lg border border-neutral-300 px-3 py-2 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
      >
        + New chat
      </button>
      <nav className="flex-1 overflow-y-auto px-2 pb-3">
        {chats.map((chat) => (
          <div
            key={chat.id}
            className={`group flex items-center justify-between rounded-lg px-2 py-1.5 text-sm ${
              chat.id === activeChatId
                ? "bg-neutral-200 dark:bg-neutral-800"
                : "hover:bg-neutral-100 dark:hover:bg-neutral-800/60"
            }`}
          >
            <button
              onClick={() => onSelect(chat.id)}
              className="min-w-0 flex-1 truncate text-left"
              title={chat.title}
            >
              {chat.title}
            </button>
            <button
              onClick={() => onDelete(chat.id)}
              aria-label={`Delete ${chat.title}`}
              className="ml-1 hidden rounded px-1 text-neutral-400 hover:text-red-500 group-hover:block"
            >
              ×
            </button>
          </div>
        ))}
        {chats.length === 0 && (
          <p className="px-2 py-4 text-xs text-neutral-400">No chats yet.</p>
        )}
      </nav>
      {footer}
    </aside>
  );
}
