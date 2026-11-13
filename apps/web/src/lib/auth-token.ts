/**
 * Right after sign-in Clerk briefly has no active session, so getToken() returns null and the
 * first API calls would go out without a bearer token (401 "Missing bearer token"). Wait a
 * short while for the session instead; after the timeout, return null and let the API refuse.
 */
export const TOKEN_WAIT_MS = 5000;
const POLL_MS = 150;

export async function tokenWhenReady(
  getToken: () => Promise<string | null>,
  timeoutMs: number = TOKEN_WAIT_MS,
  sleep: (ms: number) => Promise<void> = (ms) => new Promise((r) => setTimeout(r, ms)),
): Promise<string | null> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const token = await getToken();
    if (token || Date.now() >= deadline) return token;
    await sleep(POLL_MS);
  }
}
