import { describe, expect, it } from "vitest";

import { checkDemoGate, gateConfig, gateMessage } from "./demo-gate";

const CONFIG = { url: "http://127.0.0.1:54321", key: "k" };

function fakeFetch(body: unknown, status = 200) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status });
  };
  return { fn, calls };
}

describe("gateConfig", () => {
  it("needs both the URL and the server-only key", () => {
    expect(gateConfig({ SUPABASE_URL: "http://x/" })).toBeNull();
    expect(gateConfig({ SUPABASE_URL: "http://x/", SUPABASE_DEMO_GATE_KEY: "k" })).toEqual({ url: "http://x", key: "k" });
  });
});

describe("checkDemoGate", () => {
  it("asks demo_gate with the visitor's IP", async () => {
    const { fn, calls } = fakeFetch({ allowed: true, reason: null, available_at: null });
    expect(await checkDemoGate("203.0.113.7", CONFIG, true, fn)).toEqual({ allowed: true, reason: null, availableAt: null });
    expect(calls[0].url).toBe("http://127.0.0.1:54321/rest/v1/rpc/demo_gate");
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ ip: "203.0.113.7" });
  });

  it("passes on a refusal and when to come back", async () => {
    const { fn } = fakeFetch({ allowed: false, reason: "time", available_at: "2026-11-15T10:00:00+00:00" });
    expect(await checkDemoGate("1.2.3.4", CONFIG, true, fn)).toEqual({
      allowed: false, reason: "time", availableAt: "2026-11-15T10:00:00+00:00",
    });
  });

  it("fails closed in production when the gate is unreachable or not configured", async () => {
    const { fn } = fakeFetch({}, 500);
    expect((await checkDemoGate("1.2.3.4", CONFIG, true, fn)).allowed).toBe(false);
    const broken = async () => { throw new Error("down"); };
    expect((await checkDemoGate("1.2.3.4", CONFIG, true, broken)).allowed).toBe(false);
    expect((await checkDemoGate("1.2.3.4", null, true)).allowed).toBe(false);
    expect((await checkDemoGate("1.2.3.4", null, false)).allowed).toBe(true); // local development
  });
});

describe("gateMessage", () => {
  it("explains the refusal and the time to come back", () => {
    const msg = gateMessage({ allowed: false, reason: "budget", availableAt: "2026-11-15T10:00:00Z" }, "en-GB");
    expect(msg).toContain("budget");
    expect(msg).toContain("try again after");
    expect(gateMessage({ allowed: false, reason: "daily", availableAt: null })).toContain("all visitors");
  });
});
