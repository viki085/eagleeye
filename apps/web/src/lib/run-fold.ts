/**
 * Pure fold of SSE run events into a view (LLD §2.3). The worker persists the same
 * shape (text, citations, steps, run status), so live and reloaded messages match.
 */
import type { Citation } from "./api";

export type StepStatus = "running" | "ok" | "error" | "skipped";

export interface StepView {
  id: string;
  parentId: string | null;
  kind: string;
  name: string;
  inputSummary: string;
  status: StepStatus;
  outputSummary: string;
  durationMs: number | null;
}

export interface GuardView {
  safe: string;
  intent: string;
  route: string;
}

export interface RunView {
  runId: string;
  text: string;
  steps: readonly StepView[];
  citations: readonly Citation[];
  guard: GuardView | null;
  done: boolean;
  status: string | null;
  degraded: boolean;
  cancelled: boolean;
  replaced: boolean;
  error: string | null;
}

export interface RunEvent {
  event: string;
  data: unknown;
}

type Data = Record<string, unknown>;

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);
const num = (v: unknown): number | null => (typeof v === "number" ? v : null);

export function initialRun(runId: string): RunView {
  return {
    runId,
    text: "",
    steps: [],
    citations: [],
    guard: null,
    done: false,
    status: null,
    degraded: false,
    cancelled: false,
    replaced: false,
    error: null,
  };
}

function isCitation(d: Data): boolean {
  return typeof d.n === "number" && typeof d.chunk_id === "string" && typeof d.document_id === "string";
}

function toStatus(v: unknown): StepStatus {
  return v === "ok" || v === "error" || v === "skipped" ? v : "ok";
}

function startStep(view: RunView, d: Data): RunView {
  const step: StepView = {
    id: str(d.step_id),
    parentId: typeof d.parent_id === "string" ? d.parent_id : null,
    kind: str(d.kind),
    name: str(d.name),
    inputSummary: str(d.input_summary),
    status: "running",
    outputSummary: "",
    durationMs: null,
  };
  return { ...view, steps: [...view.steps, step] };
}

function finishStep(view: RunView, d: Data): RunView {
  const id = str(d.step_id);
  return {
    ...view,
    steps: view.steps.map((s) =>
      s.id === id
        ? { ...s, status: toStatus(d.status), outputSummary: str(d.output_summary), durationMs: num(d.duration_ms) }
        : s,
    ),
  };
}

export function foldEvent(view: RunView, evt: RunEvent): RunView {
  const d = (typeof evt.data === "object" && evt.data !== null ? evt.data : {}) as Data;
  switch (evt.event) {
    case "guard.result":
      return { ...view, guard: { safe: str(d.safe), intent: str(d.intent), route: str(d.route) } };
    case "step.started":
      return startStep(view, d);
    case "step.finished":
      return finishStep(view, d);
    case "text.delta":
      return { ...view, text: view.text + str(d.text) };
    case "text.replace":
      return { ...view, text: str(d.text), replaced: true };
    case "citation":
      return isCitation(d) ? { ...view, citations: [...view.citations, d as unknown as Citation] } : view;
    case "run.done":
      return {
        ...view,
        done: true,
        status: str(d.status, "SUCCEEDED"),
        degraded: d.degraded === true,
        cancelled: d.cancelled === true,
      };
    case "run.error":
      return { ...view, done: true, status: "FAILED", error: str(d.user_message, "The run failed.") };
    default:
      return view;
  }
}

export function foldAll(runId: string, events: readonly RunEvent[]): RunView {
  return events.reduce(foldEvent, initialRun(runId));
}
