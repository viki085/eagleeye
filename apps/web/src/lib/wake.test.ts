import { describe, expect, it } from "vitest";

import { requestWake, wakeConfig } from "./wake";

const CONFIG = { url: "https://abc.lambda-url.us-east-1.on.aws/", secret: "s".repeat(32) };

describe("wakeConfig", () => {
  it("needs an https URL and a long enough secret", () => {
    expect(wakeConfig({})).toBeNull();
    expect(wakeConfig({ WAKE_URL: "http://insecure", WAKE_SECRET: "s".repeat(32) })).toBeNull();
    expect(wakeConfig({ WAKE_URL: CONFIG.url, WAKE_SECRET: "short" })).toBeNull();
    expect(wakeConfig({ WAKE_URL: CONFIG.url, WAKE_SECRET: CONFIG.secret })).toEqual(CONFIG);
  });
});

describe("requestWake", () => {
  it("sends the shared secret and reports the machine's state", async () => {
    const seen: RequestInit[] = [];
    const ok = async (_url: string, init: RequestInit) => {
      seen.push(init);
      return new Response(JSON.stringify({ state: "starting" }));
    };
    expect(await requestWake(CONFIG, ok)).toBe("starting");
    expect((seen[0].headers as Record<string, string>)["x-wake-secret"]).toBe(CONFIG.secret);
    const running = async () => new Response(JSON.stringify({ state: "running" }));
    expect(await requestWake(CONFIG, running)).toBe("running");
  });

  it("reports refusals, failures and a missing configuration", async () => {
    expect(await requestWake(CONFIG, async () => new Response("", { status: 429 }))).toBe("refused");
    expect(await requestWake(CONFIG, async () => new Response("", { status: 500 }))).toBe("failed");
    expect(await requestWake(CONFIG, async () => { throw new Error("down"); })).toBe("failed");
    expect(await requestWake(null)).toBe("not_configured");
  });
});
