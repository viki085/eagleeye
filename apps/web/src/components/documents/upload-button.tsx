"use client";

import { useRef } from "react";

import type { DocumentScope } from "@/lib/api";

const DOC_TYPES = ".pdf,.docx,.txt,.md";
const DATA_TYPES = ".csv,.tsv,.xlsx";

interface UploadButtonProps {
  scope: DocumentScope;
  uploading: boolean;
  onUpload: (file: File) => void;
}

/** Personal: documents and data files (always private). Enterprise: documents only. */
export function UploadButton({ scope, uploading, onUpload }: UploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const personal = scope === "personal";

  return (
    <div className="flex flex-col gap-2">
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="rounded-lg border border-dashed border-neutral-400 px-3 py-2 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-600 dark:hover:bg-neutral-800"
      >
        {uploading ? "Uploading…" : personal ? "+ Upload document or data" : "+ Upload enterprise document"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={personal ? `${DOC_TYPES},${DATA_TYPES}` : DOC_TYPES}
        className="hidden"
        aria-label={personal ? "Choose a document or data file to upload" : "Choose an enterprise document"}
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onUpload(file);
        }}
      />
      <p className="text-[11px] text-neutral-400">
        {personal ? (
          <>
            PDF, Word, Markdown or text · only you can see it
            <br />
            CSV or Excel → data files for analysis
          </>
        ) : (
          "PDF, Word, Markdown or text · visible to everyone in the company"
        )}
      </p>
    </div>
  );
}
