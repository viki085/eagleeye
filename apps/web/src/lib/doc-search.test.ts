import { describe, expect, it } from "vitest";

import type { DataSource, DocumentSummary } from "./api";
import {
  clampSplit,
  filterDocuments,
  filterSources,
  joinChunks,
  overlapLength,
  tableKey,
  viewerKind,
} from "./doc-search";

const doc = (title: string, filename: string, mime = "application/pdf"): DocumentSummary =>
  ({ id: title, title, filename, mime }) as DocumentSummary;

const SOURCES: DataSource[] = [
  {
    id: "s1",
    name: "grandline_ops",
    description: "Operations warehouse",
    can_see_pii: false,
    tables: [
      {
        name: "commercial.bookings",
        description: "One row per booking.",
        row_estimate: 900000,
        columns: [
          { name: "booking_number", type: "text", description: "Booking number.", pii: false, masked: false },
          { name: "teu", type: "numeric", description: "Twenty-foot equivalent units.", pii: false, masked: false },
        ],
      },
      {
        name: "finance.claims",
        description: "Cargo claims.",
        row_estimate: 9000,
        columns: [
          { name: "claim_type", type: "text", description: "Reefer temperature deviation and others.", pii: false, masked: false },
          { name: "status", type: "text", description: "open, settled or rejected", pii: false, masked: false },
        ],
      },
    ],
  },
];

describe("filterDocuments", () => {
  const docs = [doc("Reefer Cargo Handling SOP", "reefer-sop.pdf"), doc("Code of Conduct", "conduct.pdf")];

  it("returns everything for an empty query", () => {
    expect(filterDocuments(docs, "  ")).toHaveLength(2);
  });

  it("matches every word, in any order, case-insensitively, on title or filename", () => {
    expect(filterDocuments(docs, "sop REEFER").map((d) => d.title)).toEqual(["Reefer Cargo Handling SOP"]);
    expect(filterDocuments(docs, "conduct.pdf")).toHaveLength(1);
    expect(filterDocuments(docs, "reefer conduct")).toHaveLength(0);
  });
});

describe("filterSources", () => {
  it("keeps the whole tree when the database matches", () => {
    const r = filterSources(SOURCES, "operations");
    expect(r.sources[0].tables).toHaveLength(2);
    expect(r.expanded.size).toBe(0);
  });

  it("keeps a matching table with all its columns and expands the database", () => {
    const r = filterSources(SOURCES, "claims");
    expect(r.sources[0].tables.map((t) => t.name)).toEqual(["finance.claims"]);
    expect(r.sources[0].tables[0].columns).toHaveLength(2);
    expect(r.expanded.has("s1")).toBe(true);
    expect(r.expanded.has(tableKey("s1", "finance.claims"))).toBe(false);
  });

  it("keeps only matching columns and expands their table", () => {
    const r = filterSources(SOURCES, "reefer");
    expect(r.sources[0].tables[0].columns.map((c) => c.name)).toEqual(["claim_type"]);
    expect(r.expanded.has(tableKey("s1", "finance.claims"))).toBe(true);
  });

  it("drops databases with no match", () => {
    expect(filterSources(SOURCES, "salary").sources).toEqual([]);
  });
});

describe("joinChunks", () => {
  it("removes the overlap repeated from the previous chunk and groups by heading", () => {
    const overlap = "the container is escalated to a reefer technician";
    const sections = joinChunks([
      { chunk_no: 1, content: `${overlap} and the customer is notified.`, heading_path: ["Alarms"], page: 2 },
      { chunk_no: 0, content: `Intro text. If it deviates, ${overlap}`, heading_path: ["Alarms"], page: 1 },
      { chunk_no: 2, content: "Records are kept 7 years.", heading_path: ["Records"], page: 3 },
    ]);
    expect(sections).toEqual([
      { heading: "Alarms", text: `Intro text. If it deviates, ${overlap} and the customer is notified.` },
      { heading: "Records", text: "Records are kept 7 years." },
    ]);
  });

  it("ignores short accidental matches", () => {
    expect(overlapLength("ends with the", "the start")).toBe(0);
  });
});

describe("viewerKind", () => {
  it("picks the viewer from type or extension", () => {
    expect(viewerKind(doc("a", "a.pdf"))).toBe("pdf");
    expect(viewerKind(doc("a", "a.md", "text/markdown"))).toBe("markdown");
    expect(viewerKind(doc("a", "a.txt", "text/plain"))).toBe("text");
    expect(viewerKind(doc("a", "a.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))).toBe("indexed");
  });
});

describe("clampSplit", () => {
  it("keeps both sections usable", () => {
    expect(clampSplit(0.02)).toBe(0.15);
    expect(clampSplit(0.99)).toBe(0.85);
    expect(clampSplit(0.4)).toBe(0.4);
    expect(clampSplit(Number.NaN)).toBe(0.5);
  });
});
