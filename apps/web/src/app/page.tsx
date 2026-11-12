"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Composer } from "@/components/chat/composer";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Sidebar } from "@/components/chat/sidebar";
import { SourceDrawer } from "@/components/chat/source-drawer";
import { DocumentsPanel } from "@/components/documents/documents-panel";
import { useApi } from "@/hooks/use-api";
import { useDocuments } from "@/hooks/use-documents";
import type { ChatSummary, Citation } from "@/lib/api";
import { isCitation, toUiMessage, type UiMessage } from "@/lib/messages";
import { consumeSse } from "@/lib/sse";

interface StreamState {
  runId: string;
  text: string;
  status: string | null;
  citations: readonly Citation[];
}

const STAGE_TEXT: Record<string, string> = { retrieving: "Searching documents…" };

export default function ChatPage() {
  const api = useApi();
  const docs = useDocuments(api);
  const [me, setMe] = useState<string | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [stream, setStream] = useState<StreamState | null>(null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
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
    api
      .getMe()
      .then((u) => setMe(u.id))
      .catch(() => setMe(null));
  }, [api, refreshChats]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, stream?.text, stream?.status]);

  const loadMessages = useCallback(
    async (chatId: string): Promise<UiMessage[]> => {
      const detail = await api.getChat(chatId);
      return detail.messages.map(toUiMessage);
    },
    [api],
  );

  const openChat = useCallback(
    async (chatId: string) => {
      setActiveChatId(chatId);
      setError(null);
      try {
        setMessages(await loadMessages(chatId));
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load chat");
      }
    },
    [loadMessages],
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

  const runStream = useCallback(
    async (runId: string) => {
      const body = await api.openRunStream(runId);
      let acc = "";
      let cites: readonly Citation[] = [];
      setStream({ runId, text: "", status: null, citations: [] });
      await consumeSse(body, (evt) => {
        const data = evt.data as Record<string, unknown>;
        if (evt.event === "status") {
          const stage = typeof data.stage === "string" ? data.stage : "";
          setStream((s) => (s ? { ...s, status: STAGE_TEXT[stage] ?? null } : s));
        } else if (evt.event === "text.delta") {
          acc += typeof data.text === "string" ? data.text : "";
          setStream((s) => (s ? { ...s, text: acc } : s));
        } else if (evt.event === "citation" && isCitation(data)) {
          cites = [...cites, data];
        } else if (evt.event === "chat.updated") {
          const d = data as { chat_id: string; title: string };
          setChats((prev) => prev.map((c) => (c.id === d.chat_id ? { ...c, title: d.title } : c)));
        } else if (evt.event === "run.done") {
          const done: UiMessage = { key: `run-${runId}`, role: "assistant", text: acc, citations: cites };
          setMessages((prev) => [...prev, done]);
          setStream(null);
        } else if (evt.event === "run.error") {
          setError(typeof data.user_message === "string" ? data.user_message : "The run failed.");
          setStream(null);
        }
      });
    },
    [api],
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
          { key: `local-${Date.now()}`, role: "user", text, citations: [] },
        ]);
        const { run_id } = await api.sendMessage(chatId, text, crypto.randomUUID(), docs.selectedIds);
        await runStream(run_id);
      } catch (e: unknown) {
        // Stream dropped mid-run: the run continues server-side, so recover the
        // persisted answer instead of failing the turn.
        setStream(null);
        const recovered = chatId !== null && (await recoverAfterStreamDrop(chatId));
        if (!recovered) setError(e instanceof Error ? e.message : "Send failed");
      } finally {
        setBusy(false);
      }

      async function recoverAfterStreamDrop(id: string): Promise<boolean> {
        for (let attempt = 0; attempt < 5; attempt++) {
          await new Promise((r) => setTimeout(r, 1500));
          try {
            const loaded = await loadMessages(id);
            if (loaded.at(-1)?.role === "assistant") {
              setMessages(loaded);
              return true;
            }
          } catch {
            // keep retrying
          }
        }
        return false;
      }
    },
    [api, activeChatId, refreshChats, runStream, loadMessages, docs.selectedIds],
  );

  const selectedCount = docs.selectedIds.length;
  const closeDrawer = useCallback(() => setOpenCitation(null), []);

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
                <p className="mt-1 text-sm">
                  Upload documents on the right and ask about them — answers cite their sources.
                </p>
              </div>
            )}
            {messages.map((m) => (
              <MessageBubble
                key={m.key}
                role={m.role}
                text={m.text}
                citations={m.citations}
                onOpenCitation={setOpenCitation}
              />
            ))}
            {stream !== null && (
              <MessageBubble role="assistant" text={stream.text} statusText={stream.status} streaming />
            )}
            {error !== null && (
              <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
                {error}
              </div>
            )}
          </div>
        </div>
        <Composer
          disabled={busy}
          onSend={(t) => void handleSend(t)}
          contextNote={
            selectedCount > 0
              ? `${selectedCount} document${selectedCount === 1 ? "" : "s"} selected`
              : null
          }
        />
      </main>
      <DocumentsPanel state={docs} currentUserId={me} />
      <SourceDrawer api={api} citation={openCitation} onClose={closeDrawer} />
    </div>
  );
}
