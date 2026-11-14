"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Modal } from "@/components/admin/modal";
import type { ApiClient, DocumentSummary } from "@/lib/api";
import { joinChunks, viewerKind, type TextSection } from "@/lib/doc-search";

type Loaded =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "pdf"; url: string }
  | { kind: "markdown"; text: string }
  | { kind: "text"; text: string }
  | { kind: "indexed"; sections: TextSection[] };

const PROSE =
  "prose prose-sm prose-neutral max-w-none dark:prose-invert [&_table]:text-xs [&_pre]:overflow-x-auto";

async function load(api: ApiClient, doc: DocumentSummary): Promise<Loaded> {
  const kind = viewerKind(doc);
  if (kind === "indexed") {
    if (doc.status !== "READY") {
      return { kind: "error", message: "This document is still being processed. Try again in a moment." };
    }
    return { kind, sections: joinChunks(await api.getDocumentText(doc.id)) };
  }
  const blob = await api.getDocumentFile(doc.id);
  if (kind === "pdf") {
    return { kind, url: URL.createObjectURL(new Blob([blob], { type: "application/pdf" })) };
  }
  return { kind, text: await blob.text() };
}

/** Read-only viewer: the original PDF, rendered Markdown, plain text, or Word text as indexed. */
export function DocumentViewer({ api, doc, onClose }: {
  api: ApiClient;
  doc: DocumentSummary | null;
  onClose: () => void;
}) {
  const [state, setState] = useState<Loaded>({ kind: "loading" });

  useEffect(() => {
    if (doc === null) return;
    let cancelled = false;
    let url: string | null = null;
    setState({ kind: "loading" });
    load(api, doc)
      .then((loaded) => {
        if (loaded.kind === "pdf") url = loaded.url;
        if (cancelled) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        setState(loaded);
      })
      .catch((e: unknown) => {
        if (!cancelled) setState({ kind: "error", message: e instanceof Error ? e.message : "Could not open the document." });
      });
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [api, doc]);

  const subtitle = doc
    ? [doc.filename, doc.page_count ? `${doc.page_count} pages` : null, doc.scope === "enterprise" ? "Company document" : "Personal document"]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  return (
    <Modal open={doc !== null} title={doc?.title ?? ""} subtitle={subtitle} onClose={onClose} size="xl">
      <ViewerBody state={state} />
    </Modal>
  );
}

function ViewerBody({ state }: { state: Loaded }) {
  switch (state.kind) {
    case "loading":
      return <p className="py-10 text-center text-sm text-neutral-500">Opening document…</p>;
    case "error":
      return <p className="py-10 text-center text-sm text-red-600 dark:text-red-400">{state.message}</p>;
    case "pdf":
      return (
        <iframe
          src={state.url}
          title="Document"
          className="h-[72vh] w-full rounded-md border border-neutral-200 bg-white dark:border-neutral-800"
        />
      );
    case "markdown":
      return (
        <article className={PROSE}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{state.text}</ReactMarkdown>
        </article>
      );
    case "text":
      return <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">{state.text}</pre>;
    case "indexed":
      return (
        <article className={PROSE}>
          <p className="!mt-0 text-xs text-neutral-500">Word document, shown as the text EagleEye indexed.</p>
          {state.sections.map((s, i) => (
            <section key={i}>
              {s.heading && <h3>{s.heading}</h3>}
              {s.text.split(/\n{2,}|\n(?=[-•] )/).map((para, j) => (
                <p key={j} className="whitespace-pre-wrap">{para.trim()}</p>
              ))}
            </section>
          ))}
        </article>
      );
  }
}
