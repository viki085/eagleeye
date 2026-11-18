"use client";

import { useAuth, useClerk, useSignIn } from "@clerk/nextjs";
import { isClerkAPIResponseError } from "@clerk/nextjs/errors";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { BrandPanel } from "@/components/auth/brand-panel";
import { BrandIcon } from "@/components/brand/brand-icon";
import { friendlyAuthError, safeRedirect } from "@/lib/sign-in";

type Step = "identify" | "password" | "code" | "trust";

// Muted antique gold palette (matches the EagleEye emblem): accent #9E8253, hover #B0925E,
// light text accent #C5A368. Matte: no gradients or glow beyond a soft focus ring.
const FOCUS = "outline-none focus-visible:ring-4 focus-visible:ring-[#9E8253]/25";
const FIELD =
  "w-full rounded-lg border border-black/15 bg-white px-3 py-2.5 text-sm outline-none transition placeholder:text-neutral-400 hover:border-[#9E8253]/50 focus:border-[#9E8253] focus:ring-4 focus:ring-[#9E8253]/20 dark:border-white/15 dark:bg-[#0d0d0e] dark:placeholder:text-neutral-500 dark:hover:border-[#9E8253]/50 dark:focus:border-[#9E8253]";
const PRIMARY =
  `flex w-full items-center justify-center rounded-lg bg-[#9E8253] px-3 py-2.5 text-sm font-semibold text-white transition hover:bg-[#B0925E] active:bg-[#8C7349] disabled:cursor-not-allowed disabled:bg-[#9E8253]/45 disabled:text-white/70 ${FOCUS}`;
const SECONDARY =
  `flex w-full items-center justify-center gap-2.5 rounded-lg border border-black/15 bg-white px-3 py-2.5 text-sm font-medium transition hover:border-[#9E8253]/60 hover:bg-[#9E8253]/[0.05] disabled:opacity-60 dark:border-white/15 dark:bg-transparent dark:hover:border-[#9E8253]/60 dark:hover:bg-[#C5A368]/[0.06] ${FOCUS}`;
const LINK = `rounded text-xs font-medium text-[#7d6540] underline-offset-2 hover:underline dark:text-[#C5A368] ${FOCUS}`;
const NO_ORG = "Your account isn't set up in your organisation yet. Contact your administrator.";

function messageOf(err: unknown): string {
  if (isClerkAPIResponseError(err)) {
    const first = err.errors[0];
    return friendlyAuthError(first?.code, first?.longMessage ?? first?.message);
  }
  return friendlyAuthError(undefined, err instanceof Error ? err.message : undefined);
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="h-4 w-4">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.7Z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24Z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9Z" />
    </svg>
  );
}

function Header({ title, subtitle }: { title: string; subtitle: ReactNode }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">{title}</h1>
      <p className="mt-1.5 text-sm text-neutral-500">{subtitle}</p>
    </div>
  );
}

function Strong({ children }: { children: ReactNode }) {
  return <strong className="font-medium text-neutral-700 dark:text-neutral-300">{children}</strong>;
}

export function SignInScreen() {
  const { signIn, fetchStatus } = useSignIn();
  const clerk = useClerk();
  const { isSignedIn } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const [step, setStep] = useState<Step>("identify");
  const [identifier, setIdentifier] = useState("");
  const [codeTarget, setCodeTarget] = useState(""); // masked email Clerk returns, e.g. j***@corp.com
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [hasPassword, setHasPassword] = useState(false);
  const [error, setError] = useState<string | null>(
    params.get("error") === "no_account" ? friendlyAuthError("external_account_not_found") : null,
  );
  const [notice, setNotice] = useState<string | null>(null);
  const busy = fetchStatus === "fetching";

  const target = () => safeRedirect(params.get("redirect_url"), window.location.origin);
  const go = (url: string) => {
    if (url.startsWith("http")) window.location.href = url;
    else router.push(url);
  };

  /** Clerk can leave a new session "pending" on a task. This instance requires an
   * organisation: activate the user's company organisation (admins add every new user to it). */
  async function resolveSessionTask(): Promise<void> {
    const session = clerk.session;
    if (!session || session.status !== "pending") return;
    if (session.currentTask?.key !== "choose-organization") {
      setError("Your account needs a setup step this page doesn't support. Contact your administrator.");
      return;
    }
    const memberships = await clerk.user?.getOrganizationMemberships();
    const org = memberships?.data?.[0]?.organization;
    if (!org) return setError(NO_ORG);
    await clerk.setActive({
      session: session.id,
      organization: org.id,
      navigate: ({ decorateUrl }) => go(decorateUrl(target())),
    });
  }

  useEffect(() => {
    if (isSignedIn) router.replace(target());
    else if (clerk.loaded && clerk.session?.status === "pending") void resolveSessionTask();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react to auth state only
  }, [isSignedIn, clerk.loaded, clerk.session?.status]);

  async function finish(): Promise<void> {
    const { error: err } = await signIn.finalize({
      navigate: ({ session, decorateUrl }) => {
        if (session?.currentTask) return void resolveSessionTask();
        go(decorateUrl(target()));
      },
    });
    if (err) setError(messageOf(err));
  }

  async function afterFactor(): Promise<void> {
    if (signIn.status === "complete") return finish();
    if (signIn.status === "needs_client_trust") {
      const { error: err } = await signIn.mfa.sendEmailCode();
      if (err) return setError(messageOf(err));
      setCode("");
      setNotice(`For your security, we sent a verification code to ${codeTarget || "your email"}.`);
      return setStep("trust");
    }
    if (signIn.status === "needs_second_factor") {
      return setError("Your account uses an extra verification method this page doesn't support. Contact your administrator.");
    }
    setError("Sign-in didn't complete. Please try again.");
  }

  async function sendCode(): Promise<void> {
    setError(null);
    const { error: err } = await signIn.emailCode.sendCode();
    if (err) return setError(messageOf(err));
    setCode("");
    setNotice(`We emailed a 6-digit code to ${codeTarget || "your work email"}. It expires in 10 minutes.`);
    setStep("code");
  }

  async function submitIdentifier(): Promise<void> {
    setError(null);
    setNotice(null);
    const { error: err } = await signIn.create({ identifier: identifier.trim() });
    if (err) return setError(messageOf(err));
    const factors = signIn.supportedFirstFactors ?? [];
    const emailFactor = factors.find((f) => f.strategy === "email_code");
    const passwordFactor = factors.some((f) => f.strategy === "password");
    setCodeTarget((emailFactor && "safeIdentifier" in emailFactor ? emailFactor.safeIdentifier : "") || "");
    setHasPassword(passwordFactor);
    if (passwordFactor) return setStep("password");
    if (emailFactor) return sendCode();
    setError("No sign-in method is set up for this account. Contact your administrator.");
  }

  async function submitPassword(): Promise<void> {
    setError(null);
    const { error: err } = await signIn.password({ identifier: identifier.trim(), password });
    if (err) return setError(messageOf(err));
    await afterFactor();
  }

  async function submitCode(): Promise<void> {
    setError(null);
    const { error: err } =
      step === "trust" ? await signIn.mfa.verifyEmailCode({ code }) : await signIn.emailCode.verifyCode({ code });
    if (err) return setError(messageOf(err));
    await afterFactor();
  }

  async function google(): Promise<void> {
    setError(null);
    const { error: err } = await signIn.sso({
      strategy: "oauth_google",
      redirectUrl: target(),
      redirectCallbackUrl: "/sign-in/sso-callback",
    });
    if (err) setError(messageOf(err));
  }

  async function startOver(): Promise<void> {
    // a session parked on a task blocks a new sign-in: drop it first
    if (clerk.session?.status === "pending") await clerk.signOut();
    await signIn.reset();
    setStep("identify");
    setPassword("");
    setCode("");
    setError(null);
    setNotice(null);
  }

  const onSubmit = (fn: () => Promise<void>) => (e: React.FormEvent) => {
    e.preventDefault();
    if (!busy) void fn();
  };

  return (
    <div className="flex min-h-dvh bg-[#f3f3f0] dark:bg-[#0b0b0c]">
      <BrandPanel />
      <main className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-[400px]">
          <div className="mb-8 flex items-center gap-2 lg:hidden">
            <BrandIcon size={36} />
            <span className="text-lg font-semibold tracking-tight">EagleEye</span>
          </div>
          <div className="rounded-2xl border border-[rgba(197,163,104,0.35)] bg-white p-7 shadow-[0_8px_30px_rgba(0,0,0,0.06)] dark:border-[rgba(197,163,104,0.25)] dark:bg-[#141517] dark:shadow-[0_12px_40px_rgba(0,0,0,0.45)]">
            {step === "identify" && (
              <>
                <Header title="Sign in" subtitle="Continue with Google, or use your username or work email." />
                <button type="button" onClick={() => void google()} disabled={busy} className={SECONDARY}>
                  <GoogleMark /> Continue with Google
                </button>
                <div className="my-5 flex items-center gap-3 text-[11px] uppercase tracking-[0.12em] text-neutral-400">
                  <span className="h-px flex-1 bg-black/10 dark:bg-white/10" /> or <span className="h-px flex-1 bg-black/10 dark:bg-white/10" />
                </div>
                <form onSubmit={onSubmit(submitIdentifier)} className="flex flex-col gap-4">
                  <label className="flex flex-col gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">
                    Username or work email
                    <input type="text" required autoFocus autoComplete="username" autoCapitalize="none" spellCheck={false}
                      value={identifier} onChange={(e) => setIdentifier(e.target.value)}
                      placeholder="jane_doe or name@yourcompany.com" className={FIELD} />
                  </label>
                  <button type="submit" disabled={busy || !identifier.trim()} className={PRIMARY}>{busy ? "Checking…" : "Continue"}</button>
                </form>
              </>
            )}

            {step === "password" && (
              <>
                <Header title="Enter your password" subtitle={<>Signing in as <Strong>{identifier}</Strong></>} />
                <form onSubmit={onSubmit(submitPassword)} className="flex flex-col gap-4">
                  <label className="flex flex-col gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">
                    Password
                    <input type="password" required autoFocus autoComplete="current-password" value={password}
                      onChange={(e) => setPassword(e.target.value)} className={FIELD} />
                  </label>
                  <button type="submit" disabled={busy || !password} className={PRIMARY}>{busy ? "Signing in…" : "Sign in"}</button>
                </form>
                <div className="mt-4 flex justify-between">
                  <button type="button" onClick={() => void sendCode()} className={LINK}>Email me a code instead</button>
                  <button type="button" onClick={() => void startOver()} className={LINK}>Use a different account</button>
                </div>
              </>
            )}

            {(step === "code" || step === "trust") && (
              <>
                <Header title={step === "trust" ? "Verify it's you" : "Check your email"}
                  subtitle={<>Enter the 6-digit code sent to <Strong>{codeTarget || identifier}</Strong></>} />
                <form onSubmit={onSubmit(submitCode)} className="flex flex-col gap-4">
                  <label className="flex flex-col gap-1.5 text-xs font-medium text-neutral-700 dark:text-neutral-300">
                    Verification code
                    <input inputMode="numeric" autoComplete="one-time-code" required autoFocus maxLength={6} pattern="[0-9]{6}"
                      value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      placeholder="••••••" className={`${FIELD} text-center font-mono text-lg tracking-[0.5em]`} />
                  </label>
                  <button type="submit" disabled={busy || code.length !== 6} className={PRIMARY}>{busy ? "Verifying…" : "Verify and sign in"}</button>
                </form>
                <div className="mt-4 flex justify-between">
                  <button type="button" onClick={() => void (step === "trust" ? signIn.mfa.sendEmailCode() : sendCode())} className={LINK}>Send a new code</button>
                  {hasPassword && step === "code" ? (
                    <button type="button" onClick={() => setStep("password")} className={LINK}>Use password instead</button>
                  ) : (
                    <button type="button" onClick={() => void startOver()} className={LINK}>Use a different account</button>
                  )}
                </div>
              </>
            )}

            {notice && !error && <p role="status" className="mt-4 rounded-lg border border-[rgba(197,163,104,0.25)] bg-[#9E8253]/[0.08] px-3 py-2 text-xs text-[#6b5636] dark:text-[#d6bd8f]">{notice}</p>}
            {error && <p role="alert" className="mt-4 rounded-lg bg-[#d03b3b]/10 px-3 py-2 text-xs text-[#b42f2f] dark:text-[#e66767]">{error}</p>}
            {step === "identify" && clerk.session?.status === "pending" && (
              <button type="button" onClick={() => void startOver()} className={`${LINK} mt-3`}>
                Use a different account
              </button>
            )}
          </div>
          <p className="mt-6 text-center text-xs text-neutral-500">
            No account? EagleEye access is managed by your organisation. Contact your administrator.
          </p>
        </div>
      </main>
    </div>
  );
}
