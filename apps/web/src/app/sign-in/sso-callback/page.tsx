"use client";

import { HandleSSOCallback } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

/** Return point after Google sign-in. A Google account with no EagleEye user is never signed
 * up (enterprise: no self-signup); it goes back to sign-in with an explanation. */
export default function SsoCallbackPage() {
  const router = useRouter();
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#f3f3f0] text-sm text-neutral-500 dark:bg-[#0d0d0d]">
      Signing you in…
      <HandleSSOCallback
        navigateToApp={({ decorateUrl }) => {
          const url = decorateUrl("/");
          if (url.startsWith("http")) window.location.href = url;
          else router.push(url);
        }}
        navigateToSignIn={() => router.push("/sign-in")}
        navigateToSignUp={() => router.push("/sign-in?error=no_account")}
      />
    </main>
  );
}
