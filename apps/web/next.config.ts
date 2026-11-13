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

const nextConfig: NextConfig = {
  // Dev-only badge: bottom-left would cover the avatar in the collapsed chats rail.
  devIndicators: { position: "bottom-right" },
  env: {
    NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY: process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
