"use client";

import { useAuth, useClerk, useSignIn } from "@clerk/nextjs";
import { isClerkAPIResponseError } from "@clerk/nextjs/errors";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BrandPanel } from "@/components/auth/brand-panel";
import { BrandIcon } from "@/components/brand/brand-icon";
import { friendlyAuthError } from "@/lib/sign-in";

const USERNAME = process.env.NEXT_PUBLIC_DEMO_USERNAME ?? "";
const PASSWORD = process.env.NEXT_PUBLIC_DEMO_PASSWORD ?? "";

const FOCUS = "outline-none focus-visible:ring-4 focus-visible:ring-[#9E8253]/25";
const FIELD =
  "w-full rounded-lg border border-black/15 bg-white px-3 py-2.5 text-sm outline-none transition hover:border-[#9E8253]/50 focus:border-[#9E8253] focus:ring-4 focus:ring-[#9E8253]/20 dark:border-white/15 dark:bg-[#0d0d0e] dark:focus:border-[#9E8253]";
const PRIMARY = `flex w-full items-center justify-center rounded-lg bg-[#9E8253] px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-[#B0925E] active:bg-[#8C7349] disabled:cursor-not-allowed disabled:bg-[#9E8253]/45 disabled:text-white/70 ${FOCUS}`;
const SETUP_NEEDED = "The demo isn't available right now. Please try again later.";

function messageOf(err: unknown): string {
  if (isClerkAPIResponseError(err)) {
    const first = err.errors[0];
    return friendlyAuthError(first?.code, first?.longMessage ?? first?.message);
  }
  return friendlyAuthError(undefined, err instanceof Error ? err.message : undefined);
}

function Credential({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg bg-white/70 px-3 py-2 dark:bg-black/30">
      <span className="text-xs text-neutral-500">{label}</span>
      <span className="flex items-center gap-2">
        <code className="font-mono text-sm font-semibold text-neutral-900 dark:text-neutral-50">{value}</code>
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(value).then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            });
          }}
          className={`rounded px-1.5 text-[11px] font-medium text-[#7d6540] hover:underline dark:text-[#C5A368] ${FOCUS}`}
          aria-label={`Copy ${label.toLowerCase()}`}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </span>
    </div>
  );
}

/** /demo: the public demo sign-in. The shared credentials are shown on purpose. */
export function DemoSignIn() {
  const { signIn } = useSignIn();
  const clerk = useClerk();
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const available = Boolean(USERNAME && PASSWORD);

  useEffect(() => {
    if (isSignedIn) router.replace("/");
  }, [isSignedIn, router]);

  /** This instance requires an organisation: activate the demo user's company organisation. */
  async function activateOrganisation(): Promise<void> {
    const session = clerk.session;
    if (!session || session.currentTask?.key !== "choose-organization") return setError(SETUP_NEEDED);
    const memberships = await clerk.user?.getOrganizationMemberships();
    const org = memberships?.data?.[0]?.organization;
    if (!org) return setError(SETUP_NEEDED);
    await clerk.setActive({ session: session.id, organization: org.id, navigate: () => router.push("/") });
  }

  async function submit(e: React.FormEvent): Promise<void> {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await enter();
    } finally {
      setBusy(false);
    }
  }

  async function enter(): Promise<void> {
    setError(null);
    // a session parked on a task blocks a new sign-in
    if (clerk.session?.status === "pending") await clerk.signOut();
    // the server checks the demo credentials and returns a single-use sign-in ticket
    const resp = await fetch("/api/demo-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).catch(() => null);
    const data = (await resp?.json().catch(() => null)) as { ticket?: string; error?: string } | null;
    if (!resp?.ok || !data?.ticket) return setError(data?.error ?? SETUP_NEEDED);
    const { error: err } = await signIn.ticket({ ticket: data.ticket });
    if (err) return setError(messageOf(err));
    if (signIn.status !== "complete") return setError(SETUP_NEEDED);
    const { error: finishErr } = await signIn.finalize({
      navigate: ({ session, decorateUrl }) => {
        if (session?.currentTask) return void activateOrganisation();
        router.push(decorateUrl("/"));
      },
    });
    if (finishErr) setError(messageOf(finishErr));
  }

  return (
    <div className="flex min-h-dvh bg-[#f3f3f0] dark:bg-[#0b0b0c]">
      <BrandPanel />
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-[420px]">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <BrandIcon size={36} />
            <span className="text-lg font-semibold tracking-tight">EagleEye</span>
          </div>
          <div className="rounded-2xl border border-[rgba(197,163,104,0.35)] bg-white p-7 shadow-[0_8px_30px_rgba(0,0,0,0.06)] dark:border-[rgba(197,163,104,0.25)] dark:bg-[#141517] dark:shadow-[0_12px_40px_rgba(0,0,0,0.45)]">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#7d6540] dark:text-[#C5A368]">Public demo</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">Try EagleEye</h1>
            <p className="mt-1.5 text-sm text-neutral-500">
              Explore a fictional shipping company&apos;s documents, database and data files. Suggested questions
              are waiting inside.
            </p>

            {!available ? (
              <p role="status" className="mt-6 rounded-lg bg-black/[0.04] px-3 py-2 text-sm text-neutral-600 dark:bg-white/[0.05] dark:text-neutral-300">
                The demo isn&apos;t open at the moment.
              </p>
            ) : (
              <>
                <div className="mt-5 flex flex-col gap-1.5 rounded-xl border border-[rgba(197,163,104,0.3)] bg-[#9E8253]/[0.07] p-2.5">
                  <p className="px-1 pb-0.5 text-xs font-medium text-[#6b5636] dark:text-[#d6bd8f]">Use these demo credentials</p>
                  <Credential label="Username" value={USERNAME} />
                  <Credential label="Password" value={PASSWORD} />
                  <button
                    type="button"
                    onClick={() => {
                      setUsername(USERNAME);
                      setPassword(PASSWORD);
                    }}
                    className={`mt-1 self-start rounded px-1 text-xs font-medium text-[#7d6540] underline-offset-2 hover:underline dark:text-[#C5A368] ${FOCUS}`}
                  >
                    Fill them in for me
                  </button>
                </div>
                <form onSubmit={(e) => void submit(e)} className="mt-5 flex flex-col gap-4">
                  <label className="flex flex-col gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">
                    Username
                    <input type="text" required autoComplete="username" autoCapitalize="none" spellCheck={false}
                      value={username} onChange={(e) => setUsername(e.target.value)} className={FIELD} />
                  </label>
                  <label className="flex flex-col gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">
                    Password
                    <input type="password" required autoComplete="current-password"
                      value={password} onChange={(e) => setPassword(e.target.value)} className={FIELD} />
                  </label>
                  <button type="submit" disabled={busy || !username.trim() || !password} className={PRIMARY}>
                    {busy ? "Signing in…" : "Enter the demo"}
                  </button>
                </form>
                {error && (
                  <p role="alert" className="mt-4 rounded-lg bg-[#d03b3b]/10 px-3 py-2 text-xs text-[#b42f2f] dark:text-[#e66767]">{error}</p>
                )}
              </>
            )}
          </div>
          <ul className="mt-6 flex flex-col gap-1 text-center text-xs text-neutral-500">
            <li>Your chats and uploads are private to your visit and deleted after 24 hours. Still, don&apos;t upload confidential files.</li>
            <li>Each visit has 30 minutes a day. You can come back later the same day and carry on where you left off.</li>
          </ul>
        </div>
      </main>
    </div>
  );
}
