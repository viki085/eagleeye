"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Composer } from "@/components/chat/composer";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Sidebar } from "@/components/chat/sidebar";
import { useApi } from "@/hooks/use-api";
import type { ChatSummary } from "@/lib/api";
import { consumeSse } from "@/lib/sse";

interface UiMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
}

interface StreamState {
  runId: string;
  text: string;
}

export default function ChatPage() {
  const api = useApi();
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshChats = useCallback(async () => {
    try {
      setChats(await api.listChats());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load chats");
    }
  }, [api]);

  useEffect(() => {
    void refreshChats();
  }, [refreshChats]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, stream?.text]);

  const openChat = useCallback(
    async (chatId: string) => {
      setActiveChatId(chatId);
      setError(null);
      try {
        const detail = await api.getChat(chatId);
        setMessages(
          detail.messages.map((m) => ({
            key: m.id,
            role: m.role,
            text: m.parts.parts
              .filter((p) => p.type === "text")
              .map((p) => p.text ?? "")
              .join(""),
          })),
        );
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load chat");
      }
    },
    [api],
  );

  const handleNewChat = useCallback(() => {
    setActiveChatId(null);
    setMessages([]);
    setError(null);
  }, []);

  const handleDelete = useCallback(
    async (chatId: string) => {
      try {
        await api.deleteChat(chatId);
        if (chatId === activeChatId) handleNewChat();
        await refreshChats();
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Delete failed");
      }
    },
    [api, activeChatId, handleNewChat, refreshChats],
  );

  const handleSend = useCallback(
    async (text: string) => {
      setBusy(true);
      setError(null);
      let chatId: string | null = activeChatId;
      try {
        if (chatId === null) {
          const chat = await api.createChat();
          chatId = chat.id;
          setActiveChatId(chatId);
          await refreshChats();
        }
        setMessages((prev) => [
          ...prev,
          { key: `local-${Date.now()}`, role: "user", text },
        ]);
        const { run_id } = await api.sendMessage(chatId, text, crypto.randomUUID());
        setStream({ runId: run_id, text: "" });

        const body = await api.openRunStream(run_id);
        let acc = "";
        await consumeSse(body, (evt) => {
          if (evt.event === "text.delta") {
            const delta = (evt.data as { text?: string }).text ?? "";
            acc += delta;
            setStream({ runId: run_id, text: acc });
          } else if (evt.event === "chat.updated") {
            const d = evt.data as { chat_id: string; title: string };
            setChats((prev) =>
              prev.map((c) => (c.id === d.chat_id ? { ...c, title: d.title } : c)),
            );
          } else if (evt.event === "run.done") {
            setMessages((prev) => [
              ...prev,
              { key: `run-${run_id}`, role: "assistant", text: acc },
            ]);
            setStream(null);
          } else if (evt.event === "run.error") {
            const d = evt.data as { user_message?: string };
            setError(d.user_message ?? "The run failed.");
            setStream(null);
          }
        });
      } catch (e: unknown) {
        // Stream dropped mid-run: the run continues server-side, so recover the
        // persisted answer instead of failing the turn.
        setStream(null);
        const recovered = await recoverAfterStreamDrop();
        if (!recovered) {
          setError(e instanceof Error ? e.message : "Send failed");
        }
      } finally {
        setBusy(false);
      }

      async function recoverAfterStreamDrop(): Promise<boolean> {
        if (chatId === null) return false;
        for (let attempt = 0; attempt < 5; attempt++) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            const detail = await api.getChat(chatId);
            const last = detail.messages.at(-1);
            if (last?.role === "assistant") {
              setMessages(
                detail.messages.map((m) => ({
                  key: m.id,
                  role: m.role,
                  text: m.parts.parts
                    .filter((p) => p.type === "text")
                    .map((p) => p.text ?? "")
                    .join(""),
                })),
              );
              return true;
            }
          } catch {
            // keep retrying
          }
        }
        return false;
      }
    },
    [api, activeChatId, refreshChats],
  );

  return (
    <div className="flex h-screen">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        busy={busy}
        onNewChat={handleNewChat}
        onSelect={(id) => void openChat(id)}
        onDelete={(id) => void handleDelete(id)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
            {messages.length === 0 && stream === null && (
              <div className="mt-24 text-center text-neutral-400">
                <p className="text-lg font-medium">What can I help you with?</p>
                <p className="mt-1 text-sm">Phase 1 — streaming chat over your configured LLM.</p>
              </div>
            )}
            {messages.map((m) => (
              <MessageBubble key={m.key} role={m.role} text={m.text} />
            ))}
            {stream !== null && (
              <MessageBubble role="assistant" text={stream.text} streaming />
            )}
            {error !== null && (
              <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                {error}
              </div>
            )}
          </div>
        </div>
        <Composer disabled={busy} onSend={(t) => void handleSend(t)} />
      </main>
    </div>
  );
}
