"use client";

import { useRef, useState } from "react";

import { Modal, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/admin/modal";
import type { ApiClient, BulkUserResult } from "@/lib/api";
import { CSV_TEMPLATE, MAX_CSV_ROWS, batches, parseUsersCsv, type ParsedUsers } from "@/lib/csv-users";

type Stage =
  | { kind: "choose"; error?: string }
  | { kind: "preview"; file: string; parsed: ParsedUsers }
  | { kind: "importing"; done: number; total: number; results: BulkUserResult[] }
  | { kind: "finished"; results: BulkUserResult[] };

function downloadTemplate(): void {
  const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "eagleeye-users-template.csv";
  a.click();
  URL.revokeObjectURL(url);
}

export function ImportUsersDialog({ api, open, onClose, onImported }: {
  api: ApiClient;
  open: boolean;
  onClose: () => void;
  onImported: () => void;
}) {
  const [stage, setStage] = useState<Stage>({ kind: "choose" });
  const inputRef = useRef<HTMLInputElement>(null);
  const busy = stage.kind === "importing";

  function close(): void {
    if (busy) return;
    setStage({ kind: "choose" });
    onClose();
  }

  async function readFile(file: File): Promise<void> {
    if (file.size > 2 * 1024 * 1024) {
      setStage({ kind: "choose", error: "That file is larger than 2 MB. Split it into smaller files." });
      return;
    }
    const parsed = parseUsersCsv(await file.text());
    if (parsed.fatal) setStage({ kind: "choose", error: parsed.fatal });
    else setStage({ kind: "preview", file: file.name, parsed });
  }

  async function runImport(parsed: ParsedUsers): Promise<void> {
    const total = parsed.rows.length;
    let results: BulkUserResult[] = [];
    setStage({ kind: "importing", done: 0, total, results });
    for (const batch of batches(parsed.rows)) {
      try {
        const res = await api.addUsersBulk(batch);
        results = [...results, ...res.results];
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "Request failed";
        results = [...results, ...batch.map((r) => ({ email: r.email, ok: false, error: message }))];
      }
      setStage({ kind: "importing", done: results.length, total, results });
    }
    setStage({ kind: "finished", results });
    onImported();
  }

  return (
    <Modal open={open} busy={busy} onClose={close} wide title="Import users from CSV"
      subtitle={`One user per row · columns: email (required), username, first_name, last_name, role · up to ${MAX_CSV_ROWS} rows`}>
      {stage.kind === "choose" && (
        <div className="flex flex-col gap-3">
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="flex flex-col items-center gap-1 rounded-lg border-2 border-dashed border-black/15 px-4 py-8 text-sm hover:border-[#2a78d6] hover:bg-[#2a78d6]/[0.04] dark:border-white/15"
          >
            <span className="font-semibold">Choose a CSV file</span>
            <span className="text-xs text-neutral-500">Nothing is created until you review and confirm</span>
          </button>
          <input ref={inputRef} type="file" accept=".csv,text/csv" className="hidden" aria-label="Choose a CSV file of users"
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void readFile(file);
            }} />
          {stage.error && <p role="alert" className="text-xs text-red-600 dark:text-red-400">{stage.error}</p>}
          <p className="text-xs text-neutral-500">
            Roles: member (default), knowledge_admin, data_admin, admin. A blank username is
            derived from the email (jane.doe@… → jane_doe).{" "}
            <button type="button" onClick={downloadTemplate} className="font-medium text-[#2a78d6] underline-offset-2 hover:underline">
              Download the template
            </button>
          </p>
        </div>
      )}

      {stage.kind === "preview" && (
        <div className="flex flex-col gap-3 text-sm">
          <p className="text-xs text-neutral-500">{stage.file}</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-[#0ca30c]/10 px-3 py-2">
              <p className="text-2xl font-semibold">{stage.parsed.rows.length}</p>
              <p className="text-xs text-[#006300] dark:text-[#0ca30c]">ready to add</p>
            </div>
            <div className={`rounded-lg px-3 py-2 ${stage.parsed.errors.length ? "bg-[#d03b3b]/10" : "bg-black/[0.04] dark:bg-white/[0.05]"}`}>
              <p className="text-2xl font-semibold">{stage.parsed.errors.length}</p>
              <p className="text-xs text-neutral-600 dark:text-neutral-400">rows with problems (skipped)</p>
            </div>
          </div>
          {stage.parsed.errors.length > 0 && (
            <ul className="max-h-40 overflow-y-auto rounded-md border border-black/10 text-xs dark:border-white/10">
              {stage.parsed.errors.map((e) => (
                <li key={e.line} className="flex gap-3 border-b border-black/[0.05] px-3 py-1.5 last:border-0 dark:border-white/[0.06]">
                  <span className="w-14 shrink-0 tabular-nums text-neutral-500">Line {e.line}</span>
                  <span className="min-w-0 break-words">{e.message}</span>
                </li>
              ))}
            </ul>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setStage({ kind: "choose" })} className={SECONDARY_BUTTON}>Choose another file</button>
            <button type="button" disabled={stage.parsed.rows.length === 0} onClick={() => void runImport(stage.parsed)} className={PRIMARY_BUTTON}>
              Add {stage.parsed.rows.length} user{stage.parsed.rows.length === 1 ? "" : "s"}
            </button>
          </div>
        </div>
      )}

      {stage.kind === "importing" && (
        <div role="status" className="flex flex-col gap-2 py-4 text-sm">
          <p>Adding users… {stage.done} of {stage.total}</p>
          <div className="h-2 overflow-hidden rounded-full bg-black/[0.06] dark:bg-white/10">
            <div className="h-full rounded-full bg-[#2a78d6] transition-[width]" style={{ width: `${(100 * stage.done) / Math.max(stage.total, 1)}%` }} />
          </div>
          <p className="text-xs text-neutral-500">Keep this window open until it finishes.</p>
        </div>
      )}

      {stage.kind === "finished" && <ImportResults results={stage.results} onDone={close} />}
    </Modal>
  );
}

function ImportResults({ results, onDone }: { results: BulkUserResult[]; onDone: () => void }) {
  const failed = results.filter((r) => !r.ok);
  return (
    <div className="flex flex-col gap-3 text-sm">
      <p>
        <strong>{results.length - failed.length}</strong> added
        {failed.length > 0 && <>, <strong className="text-red-600 dark:text-red-400">{failed.length}</strong> not added</>}.
      </p>
      {failed.length > 0 && (
        <ul className="max-h-48 overflow-y-auto rounded-md border border-black/10 text-xs dark:border-white/10">
          {failed.map((r, i) => (
            <li key={`${r.email}-${i}`} className="flex gap-3 border-b border-black/[0.05] px-3 py-1.5 last:border-0 dark:border-white/[0.06]">
              <span className="w-48 shrink-0 truncate">{r.email || "(no email)"}</span>
              <span className="min-w-0 break-words text-neutral-600 dark:text-neutral-400">{r.error}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="flex justify-end">
        <button type="button" onClick={onDone} className={PRIMARY_BUTTON}>Done</button>
      </div>
    </div>
  );
}
