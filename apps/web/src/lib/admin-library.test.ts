import { describe, expect, it } from "vitest";

import { DELETE_WORD, MAX_BATCH, isDeleteConfirmed, splitBatch, uploadSequentially } from "./admin-library";

describe("isDeleteConfirmed", () => {
  it("accepts exactly the word delete (surrounding spaces ignored)", () => {
    expect(DELETE_WORD).toBe("delete");
    expect(isDeleteConfirmed("delete")).toBe(true);
    expect(isDeleteConfirmed("  delete ")).toBe(true);
  });

  it("rejects anything else", () => {
    for (const text of ["", "del", "Delete", "DELETE", "delete!", "deletee", "yes"]) {
      expect(isDeleteConfirmed(text)).toBe(false);
    }
  });
});

describe("splitBatch", () => {
  it("keeps up to MAX_BATCH files and reports the rest", () => {
    const files = Array.from({ length: MAX_BATCH + 3 }, (_, i) => `f${i}`);
    const { accepted, skipped } = splitBatch(files);
    expect(accepted).toHaveLength(MAX_BATCH);
    expect(skipped).toBe(3);
    expect(splitBatch(["a"]).skipped).toBe(0);
  });
});

describe("uploadSequentially", () => {
  it("uploads one at a time, keeps going after a failure, reports each result", async () => {
    let inFlight = 0;
    let maxInFlight = 0;
    const seen: string[] = [];
    const results = await uploadSequentially(
      ["a.pdf", "bad.pdf", "c.md"],
      async (name) => {
        inFlight += 1;
        maxInFlight = Math.max(maxInFlight, inFlight);
        await Promise.resolve();
        inFlight -= 1;
        if (name === "bad.pdf") throw new Error("Unsupported file");
        return name.toUpperCase();
      },
      (r) => seen.push(`${r.item}:${r.ok ? "ok" : r.error}`),
    );
    expect(maxInFlight).toBe(1);
    expect(seen).toEqual(["a.pdf:ok", "bad.pdf:Unsupported file", "c.md:ok"]);
    expect(results.filter((r) => r.ok)).toHaveLength(2);
  });
});
