import { describe, expect, it } from "vitest";

import { isDemoVisit, timeLeftLabel } from "./demo-visit";

describe("timeLeftLabel", () => {
  it("shows whole minutes, and seconds in the last minute", () => {
    expect(timeLeftLabel(1800)).toBe("30 min left");
    expect(timeLeftLabel(61)).toBe("2 min left"); // rounds up: never says less than there is
    expect(timeLeftLabel(45)).toBe("45 s left");
    expect(timeLeftLabel(0)).toBe("time's up");
  });
});

describe("isDemoVisit", () => {
  it("accepts the heartbeat payload only", () => {
    expect(isDemoVisit({ seconds_left: 900, exhausted: null, available_at: null, message: null })).toBe(true);
    expect(isDemoVisit({ seconds_left: "900" })).toBe(false);
    expect(isDemoVisit(null)).toBe(false);
  });
});
