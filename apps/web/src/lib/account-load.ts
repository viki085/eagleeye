/** Pure helpers for loading the signed-in person's EagleEye account on the chat page. */

import { ApiError } from "./api";

export type AccountRole = "admin" | "member";

/**
 * What a failed account lookup means. Only a 403 is a real answer (signed in with Clerk, but no
 * live EagleEye account). Anything else, including no reply at all or CloudFront's error page
 * while the demo machine is off, means "check whether the server is asleep".
 */
export function accountLoadFailure(e: unknown): "no_access" | "check_server" {
  return e instanceof ApiError && e.status === 403 ? "no_access" : "check_server";
}

/** The role to show, or undefined until the account has loaded (never guess "member"). */
export function displayRole(me: { isAdmin: boolean } | null | undefined): AccountRole | undefined {
  if (!me) return undefined;
  return me.isAdmin ? "admin" : "member";
}
