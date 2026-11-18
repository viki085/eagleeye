// One-time sign-in ticket for a video employee, from Clerk's admin API (the same mechanism as
// the public demo's sign-in button). No email is sent: the ticket goes straight to the
// recording browser, works once and expires in 5 minutes. The Clerk secret key is read from
// .env.cloud and never printed.
import { readFileSync } from "node:fs";

function cloudSetting(name) {
  const env = readFileSync(new URL("../../.env.cloud", import.meta.url), "utf8");
  const line = env.split(/\r?\n/).find((l) => l.startsWith(`${name}=`));
  if (!line) throw new Error(`${name} is not set in .env.cloud`);
  return line.slice(name.length + 1).split(" #")[0].trim().replace(/^"|"$/g, "");
}

async function clerk(path, init = {}) {
  const res = await fetch(`https://api.clerk.com/v1${path}`, {
    ...init,
    headers: { Authorization: `Bearer ${cloudSetting("CLERK_SECRET_KEY")}`, "Content-Type": "application/json" },
  });
  if (!res.ok) throw new Error(`Clerk ${path}: ${res.status}`);
  return res.json();
}

export async function signInTicket(email) {
  const users = await clerk(`/users?email_address=${encodeURIComponent(email)}`);
  if (users.length !== 1) throw new Error(`expected one Clerk account for ${email}, found ${users.length}`);
  const token = await clerk("/sign_in_tokens", {
    method: "POST",
    body: JSON.stringify({ user_id: users[0].id, expires_in_seconds: 300 }),
  });
  return token.token;
}

/** Signs the page in with a ticket (call while on the site; the page then shows the app). */
export async function signInWithTicket(page, email) {
  const ticket = await signInTicket(email);
  await page.evaluate(async (t) => {
    const c = window.Clerk;
    const attempt = await c.client.signIn.create({ strategy: "ticket", ticket: t });
    if (attempt.status !== "complete") throw new Error(`sign-in status ${attempt.status}`);
    await c.setActive({ session: attempt.createdSessionId });
  }, ticket);
}
