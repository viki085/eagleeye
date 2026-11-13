"use client";

import { useState } from "react";

import { DatasetList } from "@/components/data/dataset-list";
import { ProfileModal } from "@/components/data/profile-modal";
import { SourcesList } from "@/components/data/sources-list";
import { DocumentRow } from "@/components/documents/document-row";
import { UploadButton } from "@/components/documents/upload-button";
import { useDatasets } from "@/hooks/use-datasets";
import type { DocumentsState } from "@/hooks/use-documents";
import { isDataFile, type ApiClient, type DatasetSummary } from "@/lib/api";

interface DocumentsPanelProps {
  state: DocumentsState;
  currentUserId: string | null;
  api: ApiClient;
}

export function DocumentsPanel({ state, currentUserId, api }: DocumentsPanelProps) {
  const [open, setOpen] = useState(true);
  const [profiled, setProfiled] = useState<DatasetSummary | null>(null);
  const data = useDatasets(api);
  const { documents, selectedIds } = state;
  const uploading = state.uploading || data.uploading;
  const error = state.error ?? data.error;
  const clearError = () => {
    state.clearError();
    data.clearError();
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="h-full w-10 shrink-0 border-l border-neutral-200 text-xs text-neutral-500 [writing-mode:vertical-rl] hover:bg-neutral-100 dark:border-neutral-800 dark:hover:bg-neutral-900"
      >
        Documents ({documents.length})
      </button>
    );
  }

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-l border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between p-3">
        <span className="text-sm font-semibold tracking-tight">Documents</span>
        <button
          onClick={() => setOpen(false)}
          aria-label="Collapse documents panel"
          className="rounded px-1.5 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
        >
          ›
        </button>
      </div>
      <div className="px-3 pb-3">
        <UploadButton
          uploading={uploading}
          onUpload={(f, s) => void (isDataFile(f.name) ? data.upload(f) : state.upload(f, s))}
        />
        {error !== null && (
          <div className="mt-2 flex items-start justify-between gap-2 rounded-md border border-red-300 bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            <span>{error}</span>
            <button onClick={clearError} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
      </div>
      <div className="px-3 pb-1 text-[11px] text-neutral-500">
        {selectedIds.length > 0
          ? `Answering from ${selectedIds.length} selected`
          : "Tick documents to restrict answers to them"}
      </div>
      <ul className="flex-1 overflow-y-auto px-1 pb-3">
        {documents.map((doc) => (
          <DocumentRow
            key={doc.id}
            doc={doc}
            selected={selectedIds.includes(doc.id)}
            canDelete={currentUserId !== null && doc.uploaded_by === currentUserId}
            onToggle={() => state.toggle(doc.id)}
            onDelete={() => void state.remove(doc.id)}
          />
        ))}
        {documents.length === 0 && (
          <p className="px-2 py-4 text-xs text-neutral-400">No documents yet.</p>
        )}
      </ul>
      <div className="max-h-[40%] overflow-y-auto">
        <DatasetList
          datasets={data.datasets}
          onProfile={setProfiled}
          onDelete={(d) => void data.remove(d.id)}
        />
        <SourcesList api={api} />
      </div>
      <ProfileModal api={api} dataset={profiled} onClose={() => setProfiled(null)} />
    </aside>
  );
}
