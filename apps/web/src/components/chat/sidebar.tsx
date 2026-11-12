"use client";

import { UserButton } from "@clerk/nextjs";

import type { ChatSummary } from "@/lib/api";

interface SidebarProps {
  chats: ChatSummary[];
  activeChatId: string | null;
  busy: boolean;
  onNewChat: () => void;
  onSelect: (chatId: string) => void;
  onDelete: (chatId: string) => void;
}

export function Sidebar({ chats, activeChatId, busy, onNewChat, onSelect, onDelete }: SidebarProps) {
  return (
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between p-3">
        <span className="text-sm font-semibold tracking-tight">EagleEye</span>
        <UserButton />
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
    </aside>
  );
}
