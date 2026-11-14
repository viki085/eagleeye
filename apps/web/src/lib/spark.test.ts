import { describe, expect, it } from "vitest";

import { budgetState, monotonePath, nearestIndex, ratios, scalePoints } from "./spark";

describe("scalePoints", () => {
  it("spreads buckets left to right and puts the max at the top padding", () => {
    const pts = scalePoints([0, 5, 10], 106, 56, 10, 3);
    expect(pts.map((p) => p.x)).toEqual([3, 53, 103]);
    expect(pts[0].y).toBe(53); // zero on the baseline
    expect(pts[2].y).toBe(3); // max at the top
  });

  it("keeps nulls as gaps and survives an all-zero series", () => {
    expect(Number.isNaN(scalePoints([1, null], 100, 50, 1)[1].y)).toBe(true);
    expect(scalePoints([0, 0], 100, 50, 0).every((p) => p.y === 44)).toBe(true);
  });
});

describe("monotonePath", () => {
  it("keeps a flat line flat (no overshoot)", () => {
    const path = monotonePath([{ x: 0, y: 10 }, { x: 10, y: 10 }, { x: 20, y: 10 }]);
    expect(path).toBe("M0,10 C3.3,10 6.7,10 10,10 C13.3,10 16.7,10 20,10");
  });

  it("never bends outside the range of its neighbours", () => {
    const path = monotonePath([{ x: 0, y: 50 }, { x: 10, y: 50 }, { x: 20, y: 0 }]);
    const ys = [...path.matchAll(/-?\d+(?:\.\d+)?,(-?\d+(?:\.\d+)?)/g)].map((m) => Number(m[1]));
    expect(Math.max(...ys)).toBeLessThanOrEqual(50);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0);
  });

  it("skips gaps and handles one point", () => {
    expect(monotonePath([{ x: 5, y: 5 }])).toBe("M5,5");
    expect(monotonePath([{ x: 0, y: Number.NaN }])).toBe("");
  });
});

describe("nearestIndex", () => {
  it("maps a pointer x to the closest bucket", () => {
    expect(nearestIndex(0, 106, 3, 3)).toBe(0);
    expect(nearestIndex(60, 106, 3, 3)).toBe(1);
    expect(nearestIndex(500, 106, 3, 3)).toBe(2);
  });
});

describe("budgetState", () => {
  it("turns amber past the first alert and red past the last", () => {
    expect(budgetState(0.5, [0.75, 0.9])).toBe("good");
    expect(budgetState(0.8, [0.9, 0.75])).toBe("warning");
    expect(budgetState(0.95, [0.75, 0.9])).toBe("critical");
    expect(budgetState(null, [0.75])).toBe("good");
  });
});

describe("ratios", () => {
  it("divides per bucket and leaves empty buckets null", () => {
    expect(ratios([431, 0], [1000, 0])).toEqual([0.431, null]);
  });
});
