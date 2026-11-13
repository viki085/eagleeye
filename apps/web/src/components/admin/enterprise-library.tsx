"use client";

import { useEffect, useRef, useState } from "react";

import { ConfirmDeleteDialog } from "@/components/admin/confirm-delete-dialog";
import { Panel, Pill, SectionState } from "@/components/admin/parts";
import { useAdminData } from "@/hooks/use-admin-data";
import { MAX_BATCH, splitBatch, uploadSequentially, type BatchResult } from "@/lib/admin-library";
import { count, fileSize, when } from "@/lib/admin-format";
import type { ApiClient, DocumentSummary } from "@/lib/api";

const DOC_TYPES = ".pdf,.docx,.txt,.md";
const POLL_MS = 3000;
const SETTLED = new Set(["READY", "FAILED"]);

type UploadLine = { name: string; state: "waiting" | "uploading" | "added" | "failed"; error?: string };

function statusTone(status: string): "ok" | "bad" | "warn" {
  if (status === "READY") return "ok";
  if (status === "FAILED") return "bad";
  return "warn";
}

/**
 * The company-wide knowledge base: every user's answers can cite these documents. Admins add
 * one or many at a time and delete with a typed confirmation; both are audited server-side.
 */
export function EnterpriseLibrary({ api, onChanged }: { api: ApiClient; onChanged: () => void }) {
  const [state, reload] = useAdminData(
    () => api.listDocuments().then((docs) => docs.filter((d) => d.scope === "enterprise")),
    [api],
  );
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [lines, setLines] = useState<readonly UploadLine[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<readonly DocumentSummary[] | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const docs = state.kind === "ok" ? state.data : [];
  const uploading = lines.some((l) => l.state === "waiting" || l.state === "uploading");
  const processing = docs.some((d) => !SETTLED.has(d.status));

  useEffect(() => {
    if (!processing) return; // poll only while documents are being indexed
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [processing, reload]);

  // when indexing finishes, refresh the content summary below as well
  const wasProcessing = useRef(false);
  useEffect(() => {
    if (wasProcessing.current && !processing) onChanged();
    wasProcessing.current = processing;
  }, [processing, onChanged]);

  async function upload(files: File[]): Promise<void> {
    const { accepted, skipped } = splitBatch(files);
    setNotice(skipped ? `Only ${MAX_BATCH} files per batch: ${skipped} not uploaded, add them next.` : null);
    setLines(accepted.map((f) => ({ name: f.name, state: "waiting" })));
    // lines are matched by position (File identity), so two files with one name don't collide
    const mark = (file: File, patch: Partial<UploadLine>) => {
      const index = accepted.indexOf(file);
      setLines((prev) => prev.map((l, i) => (i === index ? { ...l, ...patch } : l)));
    };
    await uploadSequentially(
      accepted,
      (file) => {
        mark(file, { state: "uploading" });
        return api.uploadDocument(file, "enterprise");
      },
      (r: BatchResult<File, DocumentSummary>) =>
        mark(r.item, r.ok ? { state: "added" } : { state: "failed", error: r.error }),
    );
    reload();
    onChanged();
  }

  async function confirmDelete(): Promise<void> {
    const targets = toDelete ?? [];
    const failed: string[] = [];
    for (const doc of targets) {
      try {
        await api.deleteDocument(doc.id);
      } catch (e: unknown) {
        failed.push(`${doc.title}: ${e instanceof Error ? e.message : "could not delete"}`);
      }
    }
    setSelected(new Set());
    reload();
    onChanged();
    if (failed.length) throw new Error(failed.join(" · "));
  }

  function toggle(id: string): void {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const allSelected = docs.length > 0 && docs.every((d) => selected.has(d.id));
  const chosen = docs.filter((d) => selected.has(d.id));

  return (
    <Panel
      title="Enterprise knowledge base"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {chosen.length > 0 && (
            <button
              type="button"
              onClick={() => setToDelete(chosen)}
              className="rounded border border-red-300 px-2 py-1 text-xs text-red-700 hover:bg-red-50 dark:border-red-900 dark:text-red-400 dark:hover:bg-red-950"
            >
              Delete selected ({chosen.length})
            </button>
          )}
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="rounded bg-neutral-900 px-2.5 py-1 text-xs font-medium text-white hover:bg-neutral-700 disabled:opacity-50 dark:bg-neutral-100 dark:text-neutral-900 dark:hover:bg-neutral-300"
          >
            {uploading ? "Uploading…" : "+ Upload documents"}
          </button>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept={DOC_TYPES}
            className="hidden"
            aria-label="Choose one or more enterprise documents"
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = "";
              if (files.length) void upload(files);
            }}
          />
        </div>
      }
    >
      <p className="mb-2 text-[11px] text-neutral-500">
        PDF, Word, Markdown or text · visible to everyone in the company · up to {MAX_BATCH} files at once
      </p>
      {notice && <p className="mb-2 text-xs text-amber-700 dark:text-amber-400">{notice}</p>}
      {lines.length > 0 && <UploadProgress lines={lines} onDismiss={uploading ? undefined : () => setLines([])} />}
      <SectionState state={state}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="py-2 text-xs text-neutral-400">No enterprise documents yet.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="text-[11px] text-neutral-500">
                  <tr>
                    <th className="w-6 px-2 py-1.5">
                      <input
                        type="checkbox"
                        aria-label="Select all documents"
                        checked={allSelected}
                        onChange={() => setSelected(allSelected ? new Set() : new Set(rows.map((d) => d.id)))}
                      />
                    </th>
                    <th className="px-2 py-1.5 font-medium">Document</th>
                    <th className="px-2 py-1.5 font-medium">Status</th>
                    <th className="px-2 py-1.5 text-right font-medium">Chunks</th>
                    <th className="px-2 py-1.5 text-right font-medium">Size</th>
                    <th className="px-2 py-1.5 font-medium">Added</th>
                    <th className="px-2 py-1.5"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => (
                    <tr key={d.id} className="border-t border-neutral-100 dark:border-neutral-800">
                      <td className="px-2 py-1.5">
                        <input
                          type="checkbox"
                          aria-label={`Select ${d.title}`}
                          checked={selected.has(d.id)}
                          onChange={() => toggle(d.id)}
                        />
                      </td>
                      <td className="max-w-[18rem] px-2 py-1.5">
                        <p className="truncate font-medium" title={d.filename}>{d.title}</p>
                        {d.error && <p className="truncate text-red-600 dark:text-red-400" title={d.error}>{d.error}</p>}
                      </td>
                      <td className="px-2 py-1.5"><Pill tone={statusTone(d.status)}>{d.status}</Pill></td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{count(d.chunk_count)}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{fileSize(d.size_bytes)}</td>
                      <td className="px-2 py-1.5 text-neutral-500">{when(d.created_at)}</td>
                      <td className="px-2 py-1.5 text-right">
                        <button
                          type="button"
                          onClick={() => setToDelete([d])}
                          aria-label={`Delete ${d.title}`}
                          className="rounded px-1.5 py-0.5 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
                        >
                          Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
      </SectionState>
      <ConfirmDeleteDialog
        names={toDelete ? toDelete.map((d) => d.title) : null}
        consequence={
          (toDelete?.length ?? 0) > 1
            ? "They are removed for everyone and can no longer be cited in answers."
            : "It is removed for everyone and can no longer be cited in answers."
        }
        onConfirm={confirmDelete}
        onClose={() => setToDelete(null)}
      />
    </Panel>
  );
}

const LINE_TEXT: Record<UploadLine["state"], string> = {
  waiting: "waiting",
  uploading: "uploading…",
  added: "added", // indexing progress shows in the table's Status column
  failed: "failed",
};

function UploadProgress({ lines, onDismiss }: { lines: readonly UploadLine[]; onDismiss?: () => void }) {
  const done = lines.filter((l) => l.state === "added").length;
  return (
    <div role="status" className="mb-3 rounded border border-neutral-200 p-2 text-xs dark:border-neutral-800">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium">Uploaded {done} of {lines.length}</span>
        {onDismiss && (
          <button type="button" onClick={onDismiss} className="text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-200">
            Dismiss
          </button>
        )}
      </div>
      <ul className="max-h-40 overflow-y-auto">
        {lines.map((l, i) => (
          <li key={`${i}-${l.name}`} className="flex justify-between gap-3 py-0.5">
            <span className="truncate">{l.name}</span>
            <span className={l.state === "failed" ? "text-right text-red-600 dark:text-red-400" : "text-neutral-500"}>
              {l.state === "failed" ? l.error ?? LINE_TEXT.failed : LINE_TEXT[l.state]}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
