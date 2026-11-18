import { describe, expect, it } from "vitest";

import { stateWhileReloading } from "./admin-data-state";

describe("stateWhileReloading", () => {
  const at = new Date();

  it("keeps the numbers on screen while a refresh loads (Live mode, slow reports)", () => {
    const shown = { kind: "ok" as const, data: { requests: 3 }, at };
    expect(stateWhileReloading(shown)).toBe(shown);
  });

  it("shows the loading state on a first load or after an error", () => {
    expect(stateWhileReloading({ kind: "loading" })).toEqual({ kind: "loading" });
    expect(stateWhileReloading({ kind: "error", message: "x" })).toEqual({ kind: "loading" });
    expect(stateWhileReloading({ kind: "forbidden" })).toEqual({ kind: "loading" });
  });
});
