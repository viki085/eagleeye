import { ApiError } from "./api";

/**
 * A cited passage that no longer exists: the document was re-indexed (new chunk ids) or
 * deleted. The citation still carries the snippet saved with the answer, so show that.
 */
export function isSourceGone(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}
