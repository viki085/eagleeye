import type { ArtifactView, ChatMessage, Citation } from "@/lib/api";
import type { RunView, StepStatus, StepView } from "@/lib/run-fold";

export interface UiMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  citations: readonly Citation[];
  artifacts: readonly ArtifactView[];
  steps: readonly StepView[];
  status: string | null;
  route: string | null;
  degraded: boolean;
  replaced: boolean;
  warnings: readonly string[];
}

interface PersistedStep {
  id?: string;
  parent_id?: string | null;
  kind?: string;
  name?: string;
  input_summary?: string;
  status?: string;
  output_summary?: string;
  duration_ms?: number;
}

function toStep(s: PersistedStep): StepView {
  const status: StepStatus = s.status === "error" || s.status === "skipped" ? s.status : "ok";
  return {
    id: s.id ?? crypto.randomUUID(),
    parentId: s.parent_id ?? null,
    kind: s.kind ?? "",
    name: s.name ?? "",
    inputSummary: s.input_summary ?? "",
    status,
    outputSummary: s.output_summary ?? "",
    durationMs: typeof s.duration_ms === "number" ? s.duration_ms : null,
  };
}

export function userMessage(text: string): UiMessage {
  return {
    key: `local-${Date.now()}`,
    role: "user",
    text,
    citations: [],
    artifacts: [],
    steps: [],
    status: null,
    route: null,
    degraded: false,
    replaced: false,
    warnings: [],
  };
}

export function fromRun(view: RunView): UiMessage {
  return {
    key: `run-${view.runId}`,
    role: "assistant",
    text: view.text,
    citations: view.citations,
    artifacts: view.artifacts,
    steps: view.steps,
    status: view.status,
    route: view.guard?.route ?? null,
    degraded: view.degraded,
    replaced: view.replaced,
    warnings: view.warnings,
  };
}

export function toUiMessage(m: ChatMessage): UiMessage {
  const parts = m.parts.parts;
  const run = parts.find((p) => p.type === "run");
  const itemsOf = (type: string): unknown[] =>
    parts.filter((p) => p.type === type).flatMap((p) => p.items ?? []);
  return {
    key: m.id,
    role: m.role,
    text: parts
      .filter((p) => p.type === "text")
      .map((p) => p.text ?? "")
      .join(""),
    citations: itemsOf("citations") as Citation[],
    artifacts: itemsOf("artifacts") as ArtifactView[],
    steps: (itemsOf("steps") as PersistedStep[]).map(toStep),
    status: typeof run?.status === "string" ? run.status : null,
    route: typeof run?.route === "string" ? run.route : null,
    degraded: run?.degraded === true,
    replaced: false,
    warnings: Array.isArray(run?.warnings) ? run.warnings : [],
  };
}
