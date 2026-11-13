import { describe, expect, it } from "vitest";

import { compare, rateDelta } from "./admin-kpi";
import { routeLabel, stepLabel } from "./admin-labels";

describe("compare (period over period)", () => {
  it("reports percentage change and whether it is good", () => {
    expect(compare(120, 100, "up")).toEqual({ pct: 20, direction: "up", tone: "good" });
    expect(compare(80, 100, "up")).toEqual({ pct: -20, direction: "down", tone: "bad" });
    expect(compare(12, 10, "down")).toEqual({ pct: 20, direction: "up", tone: "bad" });
  });

  it("treats tiny moves as flat and a missing baseline as no comparison", () => {
    expect(compare(100.2, 100, "up")).toEqual({ pct: 0.2, direction: "flat", tone: "neutral" });
    expect(compare(5, 0, "up")).toBeNull();
    expect(compare(null, 4, "up")).toBeNull();
  });
});

describe("rateDelta (percentage points)", () => {
  it("compares rates in points, not relative percent", () => {
    expect(rateDelta(0.95, 0.9, "up")).toEqual({ points: 5, direction: "up", tone: "good" });
    expect(rateDelta(0.05, 0.02, "down")).toEqual({ points: 3, direction: "up", tone: "bad" });
    expect(rateDelta(null, 0.9, "up")).toBeNull();
  });
});

describe("labels", () => {
  it("names routes and steps in platform terms, with a readable fallback", () => {
    expect(routeLabel("supervisor")).toBe("Agentic orchestration");
    expect(routeLabel("sql")).toBe("Text-to-SQL");
    expect(routeLabel("new_route")).toBe("new_route");
    expect(stepLabel("guard", "safety & intent")).toBe("Guardrail & intent classification");
    expect(stepLabel("tool", "query_database")).toBe("Text-to-SQL agent (end-to-end)");
    expect(stepLabel("tool", "some_new_tool")).toBe("some new tool");
  });
});
