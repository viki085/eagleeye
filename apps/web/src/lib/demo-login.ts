/** Server-side helpers for the public demo sign-in (/api/demo-login). */

import { timingSafeEqual } from "node:crypto";

export interface DemoCredentials {
  username: string;
  password: string;
}

/** The demo credentials configured for this deployment, or null when the demo is off. */
export function configuredDemo(env: Record<string, string | undefined>): DemoCredentials | null {
  const username = env.NEXT_PUBLIC_DEMO_USERNAME?.trim() ?? "";
  const password = env.NEXT_PUBLIC_DEMO_PASSWORD ?? "";
  return username && password ? { username, password } : null;
}

function sameText(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

/** Usernames are case-insensitive in Clerk; passwords are exact. Input is untrusted. */
export function isDemoLogin(input: unknown, demo: DemoCredentials): boolean {
  if (typeof input !== "object" || input === null) return false;
  const { username, password } = input as Record<string, unknown>;
  if (typeof username !== "string" || typeof password !== "string") return false;
  if (username.length > 64 || password.length > 128) return false;
  return sameText(username.trim().toLowerCase(), demo.username.toLowerCase()) && sameText(password, demo.password);
}

/** A small fixed-window limiter per client key (this route only issues demo tickets). */
export class WindowLimiter {
  private readonly hits = new Map<string, { start: number; count: number }>();

  constructor(
    private readonly max: number,
    private readonly windowMs: number,
  ) {}

  allow(key: string, now: number = Date.now()): boolean {
    const entry = this.hits.get(key);
    if (!entry || now - entry.start >= this.windowMs) {
      this.hits.set(key, { start: now, count: 1 });
      if (this.hits.size > 10_000) this.hits.clear(); // bounded memory
      return true;
    }
    entry.count += 1;
    return entry.count <= this.max;
  }
}
