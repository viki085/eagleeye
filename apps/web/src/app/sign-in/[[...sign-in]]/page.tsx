import { Suspense } from "react";

import { SignInScreen } from "@/components/auth/sign-in-screen";

export const metadata = { title: "Sign in · EagleEye" };

export default function SignInPage() {
  return (
    <Suspense>
      <SignInScreen />
    </Suspense>
  );
}
