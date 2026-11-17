"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { ChunkPicture } from "@/components/chat/source-drawer";
import type { ApiClient, Citation } from "@/lib/api";
import { pickVisuals } from "@/lib/source-visuals";

export const TABLE_CLASSES =
  "overflow-x-auto text-xs text-neutral-800 dark:text-neutral-200 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-neutral-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-neutral-200 [&_th]:bg-neutral-50 [&_th]:px-2 [&_th]:py-1 [&_th]:text-left dark:[&_td]:border-neutral-800 dark:[&_th]:border-neutral-800 dark:[&_th]:bg-neutral-900";

function Caption({ citation, onOpen }: { citation: Citation; onOpen: (c: Citation) => void }) {
  return (
    <button
      onClick={() => onOpen(citation)}
      className="mt-1.5 text-left text-[11px] text-neutral-500 hover:text-neutral-800 hover:underline dark:hover:text-neutral-300"
    >
      [{citation.n}] {citation.title}
      {citation.page !== null && ` · p.${citation.page}`}
    </button>
  );
}

/** A cited table's whole chunk (Markdown from the parser); hidden if the source is gone. */
function SourceTable({ api, citation }: { api: ApiClient; citation: Citation }) {
  const [content, setContent] = useState<string | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .getChunk(citation.document_id, citation.chunk_id)
      .then((chunk) => !cancelled && setContent(chunk.content))
      .catch(() => !cancelled && setGone(true));
    return () => {
      cancelled = true;
    };
  }, [api, citation.document_id, citation.chunk_id]);

  if (gone) return null;
  if (content === null) return <p className="text-xs text-neutral-400">Loading table…</p>;
  return (
    <div className={TABLE_CLASSES}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

interface SourceVisualsProps {
  api: ApiClient;
  citations: readonly Citation[];
  answer: string;
  onOpen: (c: Citation) => void;
}

/** Under an answer: the charts it read from, and the tables it used when it shows none itself. */
export function SourceVisuals({ api, citations, answer, onOpen }: SourceVisualsProps) {
  const { figures, tables } = pickVisuals(citations, answer);
  if (figures.length === 0 && tables.length === 0) return null;
  return (
    <div className="mt-3 space-y-4">
      {figures.map((c) => (
        <figure key={c.chunk_id} className="max-w-xl">
          <ChunkPicture api={api} documentId={c.document_id} chunkId={c.chunk_id} kind="image" />
          <Caption citation={c} onOpen={onOpen} />
        </figure>
      ))}
      {tables.map((c) => (
        <figure key={c.chunk_id}>
          <SourceTable api={api} citation={c} />
          <Caption citation={c} onOpen={onOpen} />
        </figure>
      ))}
    </div>
  );
}
