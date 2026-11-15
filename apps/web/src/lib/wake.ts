/**
 * Server-side: ask the wake function (an AWS Lambda behind a function URL, Phase 7B) to start
 * the sleeping demo machine. The URL and shared secret are server-only. It's idempotent: a
 * running machine is left alone. Not configured (a laptop) = "not_configured".
 */

export interface WakeConfig {
  url: string;
  secret: string;
}

export type WakeState = "starting" | "running" | "refused" | "failed" | "not_configured";

type Fetch = (input: string, init: RequestInit) => Promise<Response>;

export function wakeConfig(env: Record<string, string | undefined>): WakeConfig | null {
  const url = env.WAKE_URL?.trim() ?? "";
  const secret = env.WAKE_SECRET ?? "";
  return url.startsWith("https://") && secret.length >= 16 ? { url, secret } : null;
}

export async function requestWake(config: WakeConfig | null, fetchFn: Fetch = fetch): Promise<WakeState> {
  if (!config) return "not_configured";
  try {
    const resp = await fetchFn(config.url, {
      method: "POST",
      headers: { "x-wake-secret": config.secret, "Content-Type": "application/json" },
      body: "{}",
      cache: "no-store",
    });
    if (resp.status === 429 || resp.status === 403) return "refused"; // e.g. the daily run-time cap
    if (!resp.ok) return "failed";
    const data = (await resp.json().catch(() => ({}))) as { state?: unknown };
    return data.state === "running" ? "running" : "starting";
  } catch {
    return "failed";
  }
}
