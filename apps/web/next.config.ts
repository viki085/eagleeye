import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

// Single source of truth for config: the repo-root .env (shared with the API).
// Next only auto-loads apps/web/.env*, so merge the root file into process.env here.
function loadRootEnv(): void {
  const envPath = path.resolve(__dirname, "../../.env");
  if (!fs.existsSync(envPath)) return;
  for (const line of fs.readFileSync(envPath, "utf-8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed
      .slice(eq + 1)
      .replace(/\s+#.*$/, "")
      .trim();
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadRootEnv();

/** Clerk publishable keys encode the frontend API domain: pk_test_<base64(domain$)>. */
function clerkFrontendApi(): string {
  const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY ?? "";
  try {
    const domain = Buffer.from(key.split("_").pop() ?? "", "base64").toString("utf-8");
    return domain.replace(/\$$/, "") ? `https://${domain.replace(/\$$/, "")}` : "";
  } catch {
    return "";
  }
}

/**
 * The Clerk Account Portal (where sign-out redirects): dev `X.clerk.accounts.dev` →
 * `X.accounts.dev`; production `clerk.example.com` → `accounts.example.com`.
 */
function clerkAccountPortal(frontendApi: string): string {
  if (!frontendApi) return "";
  if (frontendApi.endsWith(".clerk.accounts.dev")) return frontendApi.replace(".clerk.accounts.dev", ".accounts.dev");
  return frontendApi.replace("://clerk.", "://accounts.");
}

function contentSecurityPolicy(): string {
  const dev = process.env.NODE_ENV !== "production";
  const api = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const clerk = clerkFrontendApi();
  const portal = clerkAccountPortal(clerk);
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    // 'unsafe-inline': Next.js bootstrap + the pre-paint theme script. 'unsafe-eval' only in
    // dev (hot reload) — production never evals (Vega runs with its AST interpreter).
    // cdn.protect.clerk.com: Clerk's bot protection, loaded by clerk-js on sign-in pages
    "script-src": ["'self'", "'unsafe-inline'", ...(dev ? ["'unsafe-eval'"] : []), clerk,
      "https://challenges.cloudflare.com", "https://cdn.protect.clerk.com"],
    // Clerk telemetry is switched off (env below), so clerk-telemetry.com is not allowed
    // *.protect.clerk.com: the bot-protection script's probes (also on port 8443)
    "connect-src": ["'self'", api, clerk, portal, "https://*.protect.clerk.com:*",
      ...(dev ? ["ws://localhost:3000"] : [])],
    "img-src": ["'self'", "data:", "blob:", "https://img.clerk.com"],
    "style-src": ["'self'", "'unsafe-inline'"],
    "font-src": ["'self'", "data:"],
    "frame-src": ["'self'", "https://challenges.cloudflare.com"],
    "worker-src": ["'self'", "blob:"],
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([name, values]) => `${name} ${values.filter(Boolean).join(" ")}`)
    .join("; ");
}

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy() },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
];

const nextConfig: NextConfig = {
  // Dev-only badge: bottom-left would cover the avatar in the collapsed chats rail.
  devIndicators: { position: "bottom-right" },
  // monorepo: trace server files from the repo root (silences the multiple-lockfiles guess)
  outputFileTracingRoot: path.resolve(__dirname, "../.."),
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  // vega-canvas has an optional server-side `canvas` import; the browser never needs it
  webpack(config) {
    return { ...config, resolve: { ...config.resolve, alias: { ...config.resolve?.alias, canvas: false } } };
  },
  env: {
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    // no usage telemetry from an enterprise app to a third party
    NEXT_PUBLIC_CLERK_TELEMETRY_DISABLED: "1",
    // sign-in/out stay on our own pages (under our CSP) instead of Clerk's hosted portal
    NEXT_PUBLIC_CLERK_SIGN_IN_URL: "/sign-in",
    NEXT_PUBLIC_CLERK_SIGN_UP_URL: "/sign-up",
  },
};

export default nextConfig;
