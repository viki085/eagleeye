import { describe, expect, it } from "vitest";

import type { Citation } from "./api";
import { hasMarkdownTable, pickVisuals } from "./source-visuals";

function cite(n: number, element_type?: Citation["element_type"], chunk = `c${n}`): Citation {
  return {
    n,
    document_id: "d",
    chunk_id: chunk,
    title: "Fleet review",
    page: 1,
    heading_path: [],
    scope: "enterprise",
    snippet: "",
    element_type,
  };
}

describe("hasMarkdownTable", () => {
  it("finds a table with its rule line", () => {
    expect(hasMarkdownTable("Rates:\n\n| Lane | Rate |\n| --- | --- |\n| A | 1 |")).toBe(true);
    expect(hasMarkdownTable("| a | b |\n|:--|--:|")).toBe(true);
  });
  it("ignores pipes in prose", () => {
    expect(hasMarkdownTable("Use a | b, or [1] | [2].")).toBe(false);
  });
});

describe("pickVisuals", () => {
  it("shows cited figures, and tables when the answer has none", () => {
    const v = pickVisuals([cite(1, "text"), cite(2, "image"), cite(3, "table"), cite(4)], "Plain answer [2][3].");
    expect(v.figures.map((c) => c.n)).toEqual([2]);
    expect(v.tables.map((c) => c.n)).toEqual([3]);
  });

  it("skips tables when the answer already has one", () => {
    const answer = "| Class | g |\n| --- | --- |\n| Feeder | 67.3 |";
    expect(pickVisuals([cite(1, "table"), cite(2, "image")], answer)).toEqual({ figures: [cite(2, "image")], tables: [] });
  });

  it("keeps one entry per chunk and caps the counts", () => {
    const many = [cite(1, "image", "x"), cite(2, "image", "x"), ...[3, 4, 5, 6].map((n) => cite(n, "image"))];
    expect(pickVisuals(many, "").figures.map((c) => c.n)).toEqual([1, 3, 4]);
    expect(pickVisuals([3, 4, 5].map((n) => cite(n, "table")), "").tables).toHaveLength(2);
  });

  it("older answers without element_type show nothing extra", () => {
    expect(pickVisuals([cite(1), cite(2)], "")).toEqual({ figures: [], tables: [] });
  });
});
