/** Pure helpers for the custom sign-in page. */

/**
 * Where to go after signing in. Only this origin's paths are allowed (open-redirect guard);
 * Clerk's middleware passes `redirect_url` as a full URL, so same-origin URLs become paths.
 */
export function safeRedirect(raw: string | null | undefined, origin: string): string {
  if (!raw) return "/";
  let path: string;
  if (raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\")) {
    path = raw;
  } else {
    try {
      const url = new URL(raw);
      if (url.origin !== origin) return "/";
      path = `${url.pathname}${url.search}`;
    } catch {
      return "/";
    }
  }
  return path.startsWith("/sign-in") ? "/" : path;
}

const MESSAGES: Record<string, string> = {
  form_identifier_not_found:
    "We couldn't find an EagleEye account with that username or email. Ask your administrator for access.",
  form_password_incorrect: "That password isn't right. Try again, or sign in with an email code.",
  form_code_incorrect: "That code isn't right. Use the most recent code we emailed you.",
  verification_expired: "That code has expired. Send a new one.",
  verification_failed: "That code didn't work. Send a new one and try again.",
  too_many_requests: "Too many attempts. Wait a minute, then try again.",
  strategy_for_user_invalid: "That sign-in method isn't available for your account.",
  form_param_format_invalid: "Enter a valid work email address.",
  session_exists: "You're already signed in.",
  external_account_not_found:
    "That Google account isn't linked to an EagleEye user. Ask your administrator for access.",
};

export function friendlyAuthError(code: string | undefined, fallback?: string): string {
  if (code && MESSAGES[code]) return MESSAGES[code];
  return fallback || "Sign-in didn't work. Please try again.";
}
