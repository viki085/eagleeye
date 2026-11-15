import { clerkClient } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

import { checkDemoGate, gateConfig, gateMessage } from "@/lib/demo-gate";
import { WindowLimiter, configuredDemo, isDemoLogin } from "@/lib/demo-login";
import { requestWake, wakeConfig } from "@/lib/wake";

/**
 * POST /api/demo-login {username, password}: when they are the public demo credentials,
 * returns a single-use Clerk sign-in ticket (60 s) for the demo user, and never for anyone
 * else. A ticket sign-in doesn't trigger Clerk's new-device email code, which demo visitors
 * could not receive; Device Trust stays on for every real account.
 */
const TICKET_TTL_S = 60;
const limiter = new WindowLimiter(10, 60_000); // per client IP

function fail(status: number, message: string): NextResponse {
  return NextResponse.json({ error: message }, { status });
}

export async function POST(req: NextRequest): Promise<NextResponse> {
  const demo = configuredDemo(process.env);
  if (!demo) return fail(404, "The demo isn't open at the moment.");
  // Vercel sets x-real-ip / x-forwarded-for to the visitor; locally it's this machine, the
  // same address the API sees, so the gate and the visits match in local testing too
  const ip =
    req.headers.get("x-real-ip")?.trim() ||
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "127.0.0.1";
  if (!limiter.allow(ip)) return fail(429, "Too many attempts. Wait a minute and try again.");

  const body: unknown = await req.json().catch(() => null);
  if (!isDemoLogin(body, demo)) return fail(401, "That isn't the demo username and password.");

  // one visit per IP per 24 hours (30 minutes, a small budget) and a daily total for everyone
  const verdict = await checkDemoGate(ip, gateConfig(process.env), process.env.NODE_ENV === "production");
  if (!verdict.allowed) {
    return NextResponse.json(
      { error: gateMessage(verdict), reason: verdict.reason, available_at: verdict.availableAt },
      { status: 403 },
    );
  }

  // start the sleeping demo machine now, so it warms up while the visitor signs in
  void requestWake(wakeConfig(process.env));

  try {
    const clerk = await clerkClient();
    const { data } = await clerk.users.getUserList({ username: [demo.username], limit: 1 });
    const user = data[0];
    if (!user) return fail(503, "The demo isn't available right now. Please try again later.");
    const token = await clerk.signInTokens.createSignInToken({ userId: user.id, expiresInSeconds: TICKET_TTL_S });
    return NextResponse.json({ ticket: token.token }, { headers: { "Cache-Control": "no-store" } });
  } catch (err: unknown) {
    console.error("demo-login: could not issue a sign-in ticket", err instanceof Error ? err.message : err);
    return fail(503, "The demo isn't available right now. Please try again later.");
  }
}
