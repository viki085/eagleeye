import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { isSourceGone } from "./citation";

describe("isSourceGone", () => {
  it("treats a 404 for the passage as re-indexed / removed", () => {
    expect(isSourceGone(new ApiError("Source not found.", 404))).toBe(true);
  });

  it("keeps real failures as errors", () => {
    expect(isSourceGone(new ApiError("Too many requests", 429))).toBe(false);
    expect(isSourceGone(new ApiError("Server error", 500))).toBe(false);
    expect(isSourceGone(new Error("network"))).toBe(false);
  });
});
