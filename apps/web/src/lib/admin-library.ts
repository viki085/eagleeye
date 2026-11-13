/** Pure helpers for the admin console's enterprise library (upload batches, delete confirm). */

/** What the admin must type to confirm a delete (as on the AWS console). */
export const DELETE_WORD = "delete";

/** Files per upload batch: matches the API's uploads limit (20 per minute per user). */
export const MAX_BATCH = 20;

export function isDeleteConfirmed(text: string): boolean {
  return text.trim() === DELETE_WORD;
}

export function splitBatch<T>(items: readonly T[]): { accepted: T[]; skipped: number } {
  return { accepted: items.slice(0, MAX_BATCH), skipped: Math.max(0, items.length - MAX_BATCH) };
}

export type BatchResult<T, R> =
  | { item: T; ok: true; value: R }
  | { item: T; ok: false; error: string };

/**
 * Uploads one file at a time (the API takes one per request and rate-limits uploads), carries
 * on after a failure, and reports each result as it lands.
 */
export async function uploadSequentially<T, R>(
  items: readonly T[],
  upload: (item: T) => Promise<R>,
  onResult: (result: BatchResult<T, R>) => void,
): Promise<BatchResult<T, R>[]> {
  const results: BatchResult<T, R>[] = [];
  for (const item of items) {
    let result: BatchResult<T, R>;
    try {
      result = { item, ok: true, value: await upload(item) };
    } catch (e: unknown) {
      result = { item, ok: false, error: e instanceof Error ? e.message : "Upload failed." };
    }
    results.push(result);
    onResult(result);
  }
  return results;
}
