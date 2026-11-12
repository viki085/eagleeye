"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { ApiClient, DocumentScope, DocumentStatus, DocumentSummary } from "@/lib/api";

const POLL_MS = 2000;
const TERMINAL: ReadonlySet<DocumentStatus> = new Set(["READY", "FAILED"]);

export interface DocumentsState {
  documents: readonly DocumentSummary[];
  selectedIds: readonly string[];
  uploading: boolean;
  error: string | null;
  upload: (file: File, scope: DocumentScope) => Promise<void>;
  remove: (docId: string) => Promise<void>;
  toggle: (docId: string) => void;
  clearError: () => void;
}

function message(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

export function useDocuments(api: ApiClient): DocumentsState {
  const [documents, setDocuments] = useState<readonly DocumentSummary[]>([]);
  const [selected, setSelected] = useState<readonly string[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const docs = await api.listDocuments();
      setDocuments(docs);
      const ready = new Set(docs.filter((d) => d.status === "READY").map((d) => d.id));
      setSelected((prev) => prev.filter((id) => ready.has(id)));
    } catch (e: unknown) {
      setError(message(e, "Failed to load documents"));
    }
  }, [api]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const processing = useMemo(
    () => documents.some((d) => !TERMINAL.has(d.status)),
    [documents],
  );

  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  const upload = useCallback(
    async (file: File, scope: DocumentScope) => {
      setUploading(true);
      setError(null);
      try {
        const doc = await api.uploadDocument(file, scope);
        setDocuments((prev) => [doc, ...prev.filter((d) => d.id !== doc.id)]);
      } catch (e: unknown) {
        setError(message(e, "Upload failed"));
      } finally {
        setUploading(false);
      }
    },
    [api],
  );

  const remove = useCallback(
    async (docId: string) => {
      setError(null);
      try {
        await api.deleteDocument(docId);
        setDocuments((prev) => prev.filter((d) => d.id !== docId));
        setSelected((prev) => prev.filter((id) => id !== docId));
      } catch (e: unknown) {
        setError(message(e, "Delete failed"));
      }
    },
    [api],
  );

  const toggle = useCallback((docId: string) => {
    setSelected((prev) =>
      prev.includes(docId) ? prev.filter((id) => id !== docId) : [...prev, docId],
    );
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { documents, selectedIds: selected, uploading, error, upload, remove, toggle, clearError };
}
