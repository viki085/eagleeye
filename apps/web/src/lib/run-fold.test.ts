import { describe, expect, it } from "vitest";

import { foldAll, foldEvent, initialRun, type RunEvent } from "./run-fold";

const supervisorRun: RunEvent[] = [
  { event: "run.started", data: { run_id: "r1" } },
  { event: "step.started", data: { step_id: "g", parent_id: null, kind: "guard", name: "safety & intent", input_summary: "q" } },
  { event: "step.finished", data: { step_id: "g", status: "ok", output_summary: "allowed · mixed · supervisor", duration_ms: 300 } },
  { event: "guard.result", data: { safe: "allowed", intent: "mixed", route: "supervisor" } },
  { event: "step.started", data: { step_id: "l1", parent_id: null, kind: "llm", name: "plan & answer" } },
  { event: "step.finished", data: { step_id: "l1", status: "ok", output_summary: "calls search_knowledge", duration_ms: 900 } },
  { event: "step.started", data: { step_id: "t1", parent_id: "l1", kind: "tool", name: "search_knowledge" } },
  { event: "step.started", data: { step_id: "t2", parent_id: "l1", kind: "tool", name: "list_documents" } },
  { event: "step.finished", data: { step_id: "t2", status: "ok", output_summary: "2 documents", duration_ms: 20 } },
  { event: "step.finished", data: { step_id: "t1", status: "error", output_summary: "timed out", duration_ms: 20000 } },
  { event: "text.delta", data: { text: "Refunds take " } },
  { event: "text.delta", data: { text: "30 days [1]." } },
  { event: "citation", data: { n: 1, document_id: "d1", chunk_id: "c1", title: "Policy", page: 1, heading_path: [], scope: "personal", snippet: "…" } },
  { event: "run.done", data: { message_id: "m1", status: "SUCCEEDED", degraded: false, cancelled: false } },
];

describe("foldEvent", () => {
  it("folds a supervisor run into text, step tree, citations and status", () => {
    const view = foldAll("r1", supervisorRun);
    expect(view.text).toBe("Refunds take 30 days [1].");
    expect(view.guard).toEqual({ safe: "allowed", intent: "mixed", route: "supervisor" });
    expect(view.steps.map((s) => [s.id, s.status])).toEqual([
      ["g", "ok"],
      ["l1", "ok"],
      ["t1", "error"],
      ["t2", "ok"],
    ]);
    expect(view.steps.find((s) => s.id === "t1")?.parentId).toBe("l1");
    expect(view.citations).toHaveLength(1);
    expect(view).toMatchObject({ done: true, status: "SUCCEEDED", cancelled: false });
  });

  it("keeps steps running until they finish", () => {
    const view = foldAll("r1", supervisorRun.slice(0, 8));
    expect(view.steps.filter((s) => s.status === "running").map((s) => s.id)).toEqual(["t1", "t2"]);
    expect(view.done).toBe(false);
  });

  it("text.replace swaps the answer and flags it", () => {
    const view = foldAll("r1", [
      { event: "text.delta", data: { text: "leaky sk-..." } },
      { event: "text.replace", data: { text: "withheld" } },
    ]);
    expect(view).toMatchObject({ text: "withheld", replaced: true });
  });

  it("records cancellation, budget and degraded outcomes", () => {
    const cancelled = foldEvent(initialRun("r"), { event: "run.done", data: { status: "CANCELLED", cancelled: true } });
    expect(cancelled).toMatchObject({ cancelled: true, status: "CANCELLED" });
    const budget = foldEvent(initialRun("r"), { event: "run.done", data: { status: "BUDGET_EXCEEDED", degraded: true } });
    expect(budget).toMatchObject({ status: "BUDGET_EXCEEDED", degraded: true });
  });

  it("run.error ends the run with a user message", () => {
    const view = foldEvent(initialRun("r"), { event: "run.error", data: { user_message: "Try again." } });
    expect(view).toMatchObject({ done: true, status: "FAILED", error: "Try again." });
  });

  it("ignores malformed and unknown events without throwing", () => {
    const view = foldAll("r", [
      { event: "citation", data: { n: "x" } },
      { event: "mystery", data: null },
      { event: "text.delta", data: { text: 42 } },
    ]);
    expect(view).toEqual(initialRun("r"));
  });

  it("collects artifacts and run warnings", () => {
    const artifact = {
      artifact_id: "a1", type: "table", title: "Orders", sql: "SELECT 1", source: "acme",
      columns: [{ name: "n", type: "int8" }], row_count: 1, truncated: false, preview: [[1]],
      assumptions: "",
    };
    const view = foldAll("r", [
      { event: "artifact", data: artifact },
      { event: "artifact", data: { artifact_id: "bad" } },
      { event: "run.done", data: { status: "SUCCEEDED", warnings: ["unverified_numbers", 3] } },
    ]);
    expect(view.artifacts.map((a) => a.artifact_id)).toEqual(["a1"]);
    expect(view.warnings).toEqual(["unverified_numbers"]);
  });

  it("collects charts and ignores malformed ones", () => {
    const chart = {
      chart_id: "c1", title: "Revenue", summary: "Highest: 130.", source_id: "a1",
      spec: { mark: { type: "line" }, data: { values: [{ x: 1, y: 2 }] } },
    };
    const view = foldAll("r", [
      { event: "chart", data: chart },
      { event: "chart", data: { chart_id: "c2", title: "x", spec: [1, 2] } },
      { event: "chart", data: { chart_id: "c3", title: "x" } },
      { event: "chart", data: null },
    ]);
    expect(view.charts.map((c) => c.chart_id)).toEqual(["c1"]);
    expect(view.charts[0].spec).toEqual(chart.spec);
  });

  it("keeps the analysis code mode on artifacts", () => {
    const view = foldAll("r", [
      {
        event: "artifact",
        data: {
          artifact_id: "a2", type: "table", title: "Gap", sql: "SELECT 1", source: "analysis",
          columns: [], row_count: 0, truncated: false, preview: [], assumptions: "", mode: "duckdb",
        },
      },
    ]);
    expect(view.artifacts[0].mode).toBe("duckdb");
  });

  it("never mutates the previous view", () => {
    const before = initialRun("r");
    const after = foldEvent(before, { event: "text.delta", data: { text: "x" } });
    expect(before.text).toBe("");
    expect(after).not.toBe(before);
  });
});
