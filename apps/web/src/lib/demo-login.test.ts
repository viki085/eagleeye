import { describe, expect, it } from "vitest";

import { WindowLimiter, configuredDemo, isDemoLogin } from "./demo-login";

const DEMO = { username: "demouser1", password: "EagleEye-demo-2026" };

describe("configuredDemo", () => {
  it("is off unless both values are set", () => {
    expect(configuredDemo({})).toBeNull();
    expect(configuredDemo({ NEXT_PUBLIC_DEMO_USERNAME: "demouser1" })).toBeNull();
    expect(
      configuredDemo({ NEXT_PUBLIC_DEMO_USERNAME: " demouser1 ", NEXT_PUBLIC_DEMO_PASSWORD: "pw" }),
    ).toEqual({ username: "demouser1", password: "pw" });
  });
});

describe("isDemoLogin", () => {
  it("accepts the demo credentials, username in any case", () => {
    expect(isDemoLogin({ username: "DemoUser1 ", password: "EagleEye-demo-2026" }, DEMO)).toBe(true);
  });

  it.each([
    [{ username: "demouser1", password: "wrong" }],
    [{ username: "admin", password: "EagleEye-demo-2026" }],
    [{ username: "demouser1", password: "eagleeye-demo-2026" }],
    [{ username: "demouser1" }],
    [{ username: 1, password: 2 }],
    [{ username: "demouser1", password: "x".repeat(500) }],
    [null],
    ["demouser1"],
  ])("rejects %j", (input) => {
    expect(isDemoLogin(input, DEMO)).toBe(false);
  });
});

describe("WindowLimiter", () => {
  it("allows up to the limit per window, then resets", () => {
    const limiter = new WindowLimiter(2, 1000);
    expect([limiter.allow("ip", 0), limiter.allow("ip", 10), limiter.allow("ip", 20)]).toEqual([true, true, false]);
    expect(limiter.allow("other", 20)).toBe(true);
    expect(limiter.allow("ip", 1000)).toBe(true);
  });
});
