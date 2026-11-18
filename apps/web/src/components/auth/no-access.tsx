"use client";

import { useClerk } from "@clerk/nextjs";
import { BrandIcon } from "@/components/brand/brand-icon";

/** Signed in with Clerk, but no EagleEye account (never provisioned, or deleted/disabled). */
export function NoAccess({ message }: { message: string }) {
  const { signOut } = useClerk();
  return (
    <main className="flex min-h-dvh items-center justify-center bg-[#f3f3f0] px-4 dark:bg-[#0d0d0d]">
      <div className="w-full max-w-md rounded-2xl border border-black/[0.08] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.06)] dark:border-white/10 dark:bg-[#1a1a19]">
        <BrandIcon size={40} className="mx-auto block" />
        <h1 className="mt-4 text-lg font-semibold">No access to EagleEye</h1>
        <p className="mt-2 text-sm text-neutral-500">{message}</p>
        <button
          type="button"
          onClick={() => void signOut({ redirectUrl: "/sign-in" })}
          className="mt-6 rounded-lg bg-[#2a78d6] px-4 py-2 text-sm font-semibold text-white hover:bg-[#1f68c0]"
        >
          Sign out
        </button>
      </div>
    </main>
  );
}
