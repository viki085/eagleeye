/**
 * Server-side: may this visitor (by IP) start or resume a demo visit right now? Asks the
 * database's demo_gate() through Supabase's REST endpoint, which stays up while the demo
 * machine sleeps. The key is server-only (never NEXT_PUBLIC); demo_gate is the one thing it
 * may call. Without configuration, production refuses (fail closed) and development allows.
 */

export interface GateVerdict {
  allowed: boolean;
  reason: "time" | "budget" | "daily" | "unavailable" | null;
  availableAt: string | null;
}

export interface GateConfig {
  url: string;
  key: string;
}

type Fetch = (input: string, init: RequestInit) => Promise<Response>;

export function gateConfig(env: Record<string, string | undefined>): GateConfig | null {
  const url = env.SUPABASE_URL?.replace(/\/+$/, "") ?? "";
  const key = env.SUPABASE_DEMO_GATE_KEY ?? "";
  return url && key ? { url, key } : null;
}

const UNAVAILABLE: GateVerdict = { allowed: false, reason: "unavailable", availableAt: null };

export async function checkDemoGate(
  ip: string,
  config: GateConfig | null,
  production: boolean,
  fetchFn: Fetch = fetch,
): Promise<GateVerdict> {
  if (!config) return production ? UNAVAILABLE : { allowed: true, reason: null, availableAt: null };
  try {
    const resp = await fetchFn(`${config.url}/rest/v1/rpc/demo_gate`, {
      method: "POST",
      headers: { apikey: config.key, Authorization: `Bearer ${config.key}`, "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
      cache: "no-store",
    });
    if (!resp.ok) return UNAVAILABLE;
    const data = (await resp.json()) as { allowed?: unknown; reason?: unknown; available_at?: unknown };
    const reason = data.reason === "time" || data.reason === "budget" || data.reason === "daily" ? data.reason : null;
    return {
      allowed: data.allowed === true,
      reason: data.allowed === true ? null : (reason ?? "unavailable"),
      availableAt: typeof data.available_at === "string" ? data.available_at : null,
    };
  } catch {
    return UNAVAILABLE;
  }
}

const REASONS: Record<Exclude<GateVerdict["reason"], null>, string> = {
  time: "Your 30 minutes of demo time for today are used up.",
  budget: "Your demo budget for AI answers is used up for today.",
  daily: "The demo has reached today's limit for all visitors.",
  unavailable: "The demo isn't available right now. Please try again later.",
};

/** The sign-in page's message, with when the visitor can come back (in their time zone). */
export function gateMessage(verdict: GateVerdict, locale?: string): string {
  const base = REASONS[verdict.reason ?? "unavailable"];
  if (!verdict.availableAt) return base;
  const when = new Date(verdict.availableAt);
  if (Number.isNaN(when.getTime())) return base;
  const text = when.toLocaleString(locale, { weekday: "short", hour: "2-digit", minute: "2-digit" });
  return `${base} You can try again after ${text}.`;
}
