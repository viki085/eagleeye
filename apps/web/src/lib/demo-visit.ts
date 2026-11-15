/** The demo visit as the app sees it: time left and whether the visit is over (no money). */

export interface DemoVisit {
  seconds_left: number;
  exhausted: "time" | "budget" | "daily" | null;
  available_at: string | null;
  message: string | null;
}

export function isDemoVisit(d: unknown): d is DemoVisit {
  return typeof d === "object" && d !== null && typeof (d as DemoVisit).seconds_left === "number";
}

/** "18 min left"; seconds in the last minute; rounds up so it never shows less than there is. */
export function timeLeftLabel(seconds: number): string {
  if (seconds <= 0) return "time's up";
  if (seconds < 60) return `${Math.ceil(seconds)} s left`;
  return `${Math.ceil(seconds / 60)} min left`;
}
