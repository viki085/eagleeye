"use client";

import { useEffect, useState } from "react";

import { DatasetList } from "@/components/data/dataset-list";
import { ProfileModal } from "@/components/data/profile-modal";
import { SourcesList } from "@/components/data/sources-list";
import { DocumentRow } from "@/components/documents/document-row";
import { DocumentViewer } from "@/components/documents/document-viewer";
import { EmptyNote, PanelSection } from "@/components/documents/panel-section";
import { ResizableSplit } from "@/components/documents/resizable-split";
import { SearchBox } from "@/components/documents/search-box";
import { UploadButton } from "@/components/documents/upload-button";
import { useDatasets } from "@/hooks/use-datasets";
import type { DocumentsState } from "@/hooks/use-documents";
import { usePanelOpen } from "@/hooks/use-panel-open";
import { filterDocuments } from "@/lib/doc-search";
import {
  isDataFile,
  type ApiClient,
  type DataSource,
  type DatasetSummary,
  type DocumentScope,
  type DocumentSummary,
} from "@/lib/api";

export interface CurrentUser {
  id: string;
  canManageEnterprise: boolean;
  isAdmin: boolean;
  isDemo?: boolean;
}

interface DocumentsPanelProps {
  state: DocumentsState;
  currentUser: CurrentUser | null;
  api: ApiClient;
}

function useSources(api: ApiClient): DataSource[] | null {
  const [sources, setSources] = useState<DataSource[] | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .listSources()
      .then((s) => !cancelled && setSources(s))
      .catch(() => !cancelled && setSources([]));
    return () => {
      cancelled = true;
    };
  }, [api]);
  return sources;
}

function ScopeTabs({ scope, onChange }: { scope: DocumentScope; onChange: (s: DocumentScope) => void }) {
  return (
    <div
      role="tablist"
      aria-label="Document scope"
      className="grid grid-cols-2 rounded-lg border border-neutral-300 p-0.5 text-xs dark:border-neutral-700"
    >
      {(["personal", "enterprise"] as const).map((s) => (
        <button
          key={s}
          role="tab"
          aria-selected={scope === s}
          onClick={() => onChange(s)}
          className={`rounded-md px-2 py-1 capitalize ${
            scope === s
              ? "bg-neutral-200 font-medium dark:bg-neutral-800"
              : "text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200"
          }`}
        >
          {s}
        </button>
      ))}
    </div>
  );
}

function DocumentList({
  docs,
  canDelete,
  state,
  empty,
  onOpen,
  selectable,
}: {
  docs: readonly DocumentSummary[];
  canDelete: (doc: DocumentSummary) => boolean;
  state: DocumentsState;
  empty: string;
  onOpen: (doc: DocumentSummary) => void;
  selectable: boolean;
}) {
  if (docs.length === 0) return <EmptyNote>{empty}</EmptyNote>;
  return (
    <ul>
      {docs.map((doc) => (
        <DocumentRow
          key={doc.id}
          doc={doc}
          canDelete={canDelete(doc)}
          onOpen={() => onOpen(doc)}
          onDelete={() => void state.remove(doc.id)}
          selection={
            selectable
              ? { selected: state.selectedIds.includes(doc.id), onToggle: () => state.toggle(doc.id) }
              : undefined
          }
        />
      ))}
    </ul>
  );
}

/**
 * Right panel. Personal tab: your documents (tick to restrict answers to them) + your data
 * files. Enterprise tab, view only: company documents + the databases you can query, filtered
 * by one search box. Clicking a document opens it in the viewer. Each tab's two sections are
 * split by a draggable divider. Enterprise upload/delete only for knowledge admins (the API
 * enforces the same rule).
 */
export function DocumentsPanel({ state, currentUser, api }: DocumentsPanelProps) {
  const [open, setOpen] = usePanelOpen("documents");
  const [scope, setScope] = useState<DocumentScope>("personal");
  const [profiled, setProfiled] = useState<DatasetSummary | null>(null);
  const [viewing, setViewing] = useState<DocumentSummary | null>(null);
  const [query, setQuery] = useState("");
  const data = useDatasets(api);
  const sources = useSources(api);
  const { documents, selectedIds } = state;
  const personalSelected = selectedIds.filter((id) =>
    documents.some((d) => d.id === id && d.scope === "personal"),
  ).length;
  const canManage = currentUser?.canManageEnterprise ?? false;
  const personalDocs = documents.filter(
    (d) => d.scope === "personal" && currentUser !== null && d.owner_id === currentUser.id,
  );
  const enterpriseDocs = documents.filter((d) => d.scope === "enterprise");
  const shownEnterprise = filterDocuments(enterpriseDocs, query);
  const searching = query.trim().length > 0;
  const uploading = state.uploading || data.uploading;
  const error = state.error ?? data.error;
  const clearError = () => {
    state.clearError();
    data.clearError();
  };
  const hint =
    personalSelected > 0
      ? `Answering from ${personalSelected} selected`
      : "Tick documents to restrict answers to them";

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="h-full w-10 shrink-0 border-l border-neutral-200 text-xs text-neutral-500 [writing-mode:vertical-rl] hover:bg-neutral-100 dark:border-neutral-800 dark:hover:bg-neutral-900"
      >
        Documents & data ({documents.length + data.datasets.length})
      </button>
    );
  }

  return (
    <aside className="flex h-full w-72 shrink-0 flex-col border-l border-neutral-200 bg-neutral-50 dark:border-neutral-800 dark:bg-neutral-900">
      <div className="flex items-center justify-between p-3">
        <span className="text-sm font-semibold tracking-tight">Documents & data</span>
        <button
          onClick={() => setOpen(false)}
          aria-label="Collapse documents panel"
          className="rounded px-1.5 text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200"
        >
          ›
        </button>
      </div>
      <div className="flex flex-col gap-2 px-3 pb-2">
        <ScopeTabs scope={scope} onChange={setScope} />
        {scope === "personal" ? (
          <UploadButton
            scope="personal"
            uploading={uploading}
            onUpload={(f) => void (isDataFile(f.name) ? data.upload(f) : state.upload(f, "personal"))}
          />
        ) : canManage ? (
          <UploadButton
            scope="enterprise"
            uploading={uploading}
            onUpload={(f) => void state.upload(f, "enterprise")}
          />
        ) : (
          <p className="rounded-lg border border-neutral-200 px-3 py-2 text-[11px] text-neutral-500 dark:border-neutral-800">
            Company documents shared with everyone. Only knowledge admins can add or remove them.
          </p>
        )}
        {error !== null && (
          <div className="flex items-start justify-between gap-2 rounded-md border border-red-300 bg-red-50 px-2 py-1.5 text-xs text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
            <span>{error}</span>
            <button onClick={clearError} aria-label="Dismiss error">
              ×
            </button>
          </div>
        )}
      </div>
      {scope === "enterprise" && (
        <div className="px-3 pb-2">
          <SearchBox
            value={query}
            onChange={setQuery}
            placeholder="Search documents, databases, tables, columns"
            label="Search company documents and data sources"
          />
        </div>
      )}
      <div className="flex min-h-0 flex-1 flex-col border-t border-neutral-200 dark:border-neutral-800">
        {scope === "personal" ? (
          <ResizableSplit
            storageKey="personal"
            top={
              <PanelSection title="My documents" count={personalDocs.length} hint={hint}>
                <DocumentList
                  docs={personalDocs}
                  canDelete={() => true}
                  state={state}
                  empty="No documents yet."
                  onOpen={setViewing}
                  selectable
                />
              </PanelSection>
            }
            bottom={
              <PanelSection title="My data files" count={data.datasets.length}>
                <DatasetList
                  datasets={data.datasets}
                  onProfile={setProfiled}
                  onDelete={(d) => void data.remove(d.id)}
                />
              </PanelSection>
            }
          />
        ) : (
          <ResizableSplit
            storageKey="enterprise"
            top={
              <PanelSection
                title="Enterprise documents"
                count={enterpriseDocs.length}
                countLabel={searching ? `${shownEnterprise.length} of ${enterpriseDocs.length}` : undefined}
                hint="Click a document to read it"
              >
                <DocumentList
                  docs={shownEnterprise}
                  canDelete={() => canManage}
                  state={state}
                  empty={searching ? `No documents match "${query.trim()}".` : "No enterprise documents yet."}
                  onOpen={setViewing}
                  selectable={false}
                />
              </PanelSection>
            }
            bottom={
              <PanelSection title="Data sources" count={sources?.length}>
                <SourcesList sources={sources} query={query} />
              </PanelSection>
            }
          />
        )}
      </div>
      <DocumentViewer api={api} doc={viewing} onClose={() => setViewing(null)} />
      <ProfileModal api={api} dataset={profiled} onClose={() => setProfiled(null)} />
    </aside>
  );
}
