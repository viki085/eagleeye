import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

import { WindowLimiter } from "@/lib/demo-login";
import { requestWake, wakeConfig } from "@/lib/wake";

/**
 * POST /api/wake: start the sleeping demo machine (Phase 7 wake/sleep). Signed-in users only
 * (demo visitors are signed in by then; their gate was checked at sign-in). The wake function
 * itself caps the machine's running time per day.
 */
const limiter = new WindowLimiter(6, 60_000); // per user

export async function POST(): Promise<NextResponse> {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ error: "Sign in first." }, { status: 401 });
  if (!limiter.allow(userId)) return NextResponse.json({ state: "starting" }); // already asked
  const state = await requestWake(wakeConfig(process.env));
  return NextResponse.json({ state }, { headers: { "Cache-Control": "no-store" } });
}
