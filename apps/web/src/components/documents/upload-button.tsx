"use client";

import { useRef, useState } from "react";

import type { DocumentScope } from "@/lib/api";

const ACCEPT = ".pdf,.docx,.txt,.md,.csv,.tsv,.xlsx";

interface UploadButtonProps {
  uploading: boolean;
  onUpload: (file: File, scope: DocumentScope) => void;
}

export function UploadButton({ uploading, onUpload }: UploadButtonProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [scope, setScope] = useState<DocumentScope>("personal");

  return (
    <div className="flex flex-col gap-2">
      <div
        role="radiogroup"
        aria-label="Document scope"
        className="grid grid-cols-2 rounded-lg border border-neutral-300 p-0.5 text-xs dark:border-neutral-700"
      >
        {(["personal", "enterprise"] as const).map((s) => (
          <button
            key={s}
            role="radio"
            aria-checked={scope === s}
            onClick={() => setScope(s)}
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
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="rounded-lg border border-dashed border-neutral-400 px-3 py-2 text-sm font-medium hover:bg-neutral-100 disabled:opacity-50 dark:border-neutral-600 dark:hover:bg-neutral-800"
      >
        {uploading ? "Uploading…" : "+ Upload document or data"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept={ACCEPT}
        className="hidden"
        aria-label="Choose a document to upload"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (file) onUpload(file, scope);
        }}
      />
      <p className="text-[11px] text-neutral-400">
        PDF, Word, Markdown or text · {scope === "personal" ? "only you can see it" : "visible to everyone"}
        <br />
        CSV or Excel → data files for analysis (always private)
      </p>
    </div>
  );
}
