"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationChips } from "@/components/chat/citation-chips";
import { StepTree } from "@/components/chat/step-tree";
import { ChartCard } from "@/components/charts/chart-card";
import { ArtifactList } from "@/components/data/artifact-list";
import type { ArtifactView, ChartView, Citation } from "@/lib/api";
import type { StepView } from "@/lib/run-fold";

interface MessageBubbleProps {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
  citations?: readonly Citation[];
  artifacts?: readonly ArtifactView[];
  charts?: readonly ChartView[];
  steps?: readonly StepView[];
  status?: string | null;
  route?: string | null;
  degraded?: boolean;
  replaced?: boolean;
  warnings?: readonly string[];
  onOpenCitation?: (citation: Citation) => void;
  onViewArtifact?: (artifact: ArtifactView) => void;
  onDownloadArtifact?: (artifact: ArtifactView) => void;
}

function Notice({ tone, children }: { tone: "warn" | "muted"; children: React.ReactNode }) {
  const cls =
    tone === "warn"
      ? "border-amber-300 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-300"
      : "border-neutral-200 bg-neutral-50 text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900";
  return <div className={`mt-2 rounded-md border px-2.5 py-1 text-xs ${cls}`}>{children}</div>;
}

function Notices({
  status,
  degraded,
  replaced,
  warnings = [],
}: Pick<MessageBubbleProps, "status" | "degraded" | "replaced" | "warnings">) {
  return (
    <>
      {warnings.includes("unverified_numbers") && (
        <Notice tone="warn">
          Some figures in this answer couldn&apos;t be matched to the results — check them against the table.
        </Notice>
      )}
      {status === "BUDGET_EXCEEDED" && (
        <Notice tone="warn">Reached the work limit — this answer may be incomplete.</Notice>
      )}
      {status === "CANCELLED" && <Notice tone="muted">Stopped</Notice>}
      {degraded && <Notice tone="warn">Answered by a fallback model (degraded mode).</Notice>}
      {replaced && <Notice tone="muted">Part of this answer was adjusted by a safety check.</Notice>}
    </>
  );
}

export function MessageBubble({
  role,
  text,
  streaming = false,
  citations = [],
  artifacts = [],
  charts = [],
  steps = [],
  status = null,
  route = null,
  degraded = false,
  replaced = false,
  warnings = [],
  onOpenCitation,
  onViewArtifact,
  onDownloadArtifact,
}: MessageBubbleProps) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl bg-blue-600 px-4 py-2 text-sm text-white">
          {text}
        </div>
      </div>
    );
  }
  const refusal = route === "blocked";
  return (
    <div className="flex">
      <div className="min-w-0 max-w-[85%] flex-1">
        <StepTree steps={steps} live={streaming} />
        <div
          className={`prose prose-sm prose-neutral max-w-none dark:prose-invert [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-neutral-100 [&_pre]:p-3 dark:[&_pre]:bg-neutral-900 ${
            refusal ? "italic text-neutral-500" : ""
          }`}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
          {streaming && <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-neutral-400" />}
        </div>
        {charts.map((c) => (
          <ChartCard key={c.chart_id} chart={c} />
        ))}
        <ArtifactList
          artifacts={artifacts}
          onView={(x) => onViewArtifact?.(x)}
          onDownload={(x) => onDownloadArtifact?.(x)}
        />
        {onOpenCitation && <CitationChips citations={citations} onOpen={onOpenCitation} />}
        {!streaming && (
          <Notices status={status} degraded={degraded} replaced={replaced} warnings={warnings} />
        )}
      </div>
    </div>
  );
}
