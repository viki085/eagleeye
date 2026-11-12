import type { ChatMessage, Citation } from "@/lib/api";
import type { RunView, StepStatus, StepView } from "@/lib/run-fold";

export interface UiMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
  citations: readonly Citation[];
  steps: readonly StepView[];
  status: string | null;
  route: string | null;
  degraded: boolean;
  replaced: boolean;
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
    steps: [],
    status: null,
    route: null,
    degraded: false,
    replaced: false,
  };
}

export function fromRun(view: RunView): UiMessage {
  return {
    key: `run-${view.runId}`,
    role: "assistant",
    text: view.text,
    citations: view.citations,
    steps: view.steps,
    status: view.status,
    route: view.guard?.route ?? null,
    degraded: view.degraded,
    replaced: view.replaced,
  };
}

export function toUiMessage(m: ChatMessage): UiMessage {
  const parts = m.parts.parts;
  const run = parts.find((p) => p.type === "run");
  return {
    key: m.id,
    role: m.role,
    text: parts
      .filter((p) => p.type === "text")
      .map((p) => p.text ?? "")
      .join(""),
    citations: parts.filter((p) => p.type === "citations").flatMap((p) => (p.items ?? []) as Citation[]),
    steps: parts
      .filter((p) => p.type === "steps")
      .flatMap((p) => (p.items ?? []) as PersistedStep[])
      .map(toStep),
    status: typeof run?.status === "string" ? run.status : null,
    route: typeof run?.route === "string" ? run.route : null,
    degraded: run?.degraded === true,
    replaced: false,
  };
}
