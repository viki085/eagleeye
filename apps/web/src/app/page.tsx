"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { NoAccess } from "@/components/auth/no-access";
import { Composer } from "@/components/chat/composer";
import { MessageBubble } from "@/components/chat/message-bubble";
import { Sidebar } from "@/components/chat/sidebar";
import { SourceDrawer } from "@/components/chat/source-drawer";
import { ArtifactModal } from "@/components/data/artifact-modal";
import { DemoBanner, DemoQuestions } from "@/components/demo/demo-welcome";
import { DocumentsPanel, type CurrentUser } from "@/components/documents/documents-panel";
import { UsagePanel } from "@/components/usage/usage-panel";
import { useApi } from "@/hooks/use-api";
import { useDocuments } from "@/hooks/use-documents";
import { useUsage } from "@/hooks/use-usage";
import { ApiError, type ArtifactView, type ChatSummary, type Citation } from "@/lib/api";
import { fromRun, toUiMessage, userMessage, type UiMessage } from "@/lib/messages";
import { foldEvent, initialRun, type RunView } from "@/lib/run-fold";
import { consumeSse } from "@/lib/sse";

export default function ChatPage() {
  const api = useApi();
  const docs = useDocuments(api);
  const [usageKey, setUsageKey] = useState(0);
  const usage = useUsage(api, usageKey);
  const [me, setMe] = useState<CurrentUser | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [stream, setStream] = useState<RunView | null>(null);
  const [openCitation, setOpenCitation] = useState<Citation | null>(null);
  const [openArtifact, setOpenArtifact] = useState<ArtifactView | null>(null);
  const downloadArtifact = useCallback(
    (a: ArtifactView) => {
      api.downloadArtifactCsv(a.artifact_id, a.title).catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Download failed");
      });
    },
    [api],
  );
  const [error, setError] = useState<string | null>(null);
  const [noAccess, setNoAccess] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<{ text: string; id: number } | null>(null);
  const isDemo = me?.isDemo === true;
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
      .then((u) =>
        setMe({
          id: u.id,
          canManageEnterprise: u.can_manage_enterprise === true,
          isAdmin: u.role === "admin",
          isDemo: u.is_demo === true,
        }),
      )
      .catch((e: unknown) => {
        setMe(null);
        // 403 here means signed in with Clerk but no (live) EagleEye account
        if (e instanceof ApiError && e.status === 403) setNoAccess(e.message.replace(/ \(request [^)]*\)$/, ""));
      });
  }, [api, refreshChats]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages, stream?.text, stream?.steps.length]);

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
      let view = initialRun(runId);
      setStream(view);
      await consumeSse(body, (evt) => {
        if (evt.event === "chat.updated") {
          const d = evt.data as { chat_id: string; title: string };
          setChats((prev) => prev.map((c) => (c.id === d.chat_id ? { ...c, title: d.title } : c)));
          return;
        }
        view = foldEvent(view, evt);
        if (evt.event === "run.done") {
          const done = fromRun(view);
          setMessages((prev) => [...prev, done]);
          setStream(null);
          setUsageKey((k) => k + 1);
        } else if (evt.event === "run.error") {
          setError(view.error);
          setStream(null);
          setUsageKey((k) => k + 1);
        } else {
          setStream(view);
        }
      });
    },
    [api],
  );

  const handleStop = useCallback(async () => {
    if (stream === null) return;
    try {
      await api.cancelRun(stream.runId);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Couldn't stop the answer");
    }
  }, [api, stream]);

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
        let runId: string;
        try {
          ({ run_id: runId } = await api.sendMessage(chatId, text, crypto.randomUUID(), docs.selectedIds));
        } catch (e: unknown) {
          // Rejected before a run started (409 busy, 429, 422…): nothing to recover.
          setError(e instanceof ApiError ? e.message : "Send failed");
          return;
        }
        setMessages((prev) => [...prev, userMessage(text)]);
        await runStream(runId);
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
  const closeArtifact = useCallback(() => setOpenArtifact(null), []);

  if (noAccess) return <NoAccess message={noAccess} />;

  return (
    // relative + overflow-hidden: the shell is exactly one screen; nothing inside it (e.g. an
    // absolutely positioned element) can stretch the page and make the whole layout scroll
    <div className="relative flex h-screen overflow-hidden">
      <Sidebar
        chats={chats}
        activeChatId={activeChatId}
        busy={busy}
        isAdmin={me?.isAdmin ?? false}
        isDemo={isDemo}
        onNewChat={handleNewChat}
        onSelect={(id) => void openChat(id)}
        onDelete={(id) => void handleDelete(id)}
        footer={<UsagePanel state={usage} />}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        {isDemo && <DemoBanner usage={usage.usage} />}
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-6">
            {messages.length === 0 && stream === null && isDemo && (
              <DemoQuestions onPick={(text) => setDraft((d) => ({ text, id: (d?.id ?? 0) + 1 }))} />
            )}
            {messages.length === 0 && stream === null && !isDemo && (
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
                steps={m.steps}
                status={m.status}
                route={m.route}
                degraded={m.degraded}
                replaced={m.replaced}
                artifacts={m.artifacts}
                charts={m.charts}
                warnings={m.warnings}
                onOpenCitation={setOpenCitation}
                onViewArtifact={setOpenArtifact}
                onDownloadArtifact={downloadArtifact}
              />
            ))}
            {stream !== null && (
              <MessageBubble
                role="assistant"
                text={stream.text}
                steps={stream.steps}
                artifacts={stream.artifacts}
                charts={stream.charts}
                route={stream.guard?.route ?? null}
                onViewArtifact={setOpenArtifact}
                onDownloadArtifact={downloadArtifact}
                streaming
              />
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
          running={stream !== null}
          onStop={() => void handleStop()}
          draft={draft}
          contextNote={
            selectedCount > 0
              ? `${selectedCount} document${selectedCount === 1 ? "" : "s"} selected`
              : null
          }
        />
      </main>
      <DocumentsPanel state={docs} currentUser={me} api={api} />
      <SourceDrawer api={api} citation={openCitation} onClose={closeDrawer} />
      <ArtifactModal
        api={api}
        artifact={openArtifact}
        onClose={closeArtifact}
        onDownload={downloadArtifact}
      />
    </div>
  );
}
