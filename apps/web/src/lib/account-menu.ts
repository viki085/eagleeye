/** Pure helpers for the account menu: placement, initials and keyboard navigation. */

export type MenuPlacement = "below" | "right";

/** CSS for a `position: fixed` panel. */
export interface MenuPosition {
  top?: number;
  bottom?: number;
  left: number;
}

interface Rect {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

const GAP = 8;
const EDGE = 8;

/** Places the panel next to the trigger, kept inside the viewport horizontally. */
export function menuPosition(
  trigger: Rect,
  placement: MenuPlacement,
  width: number,
  viewportWidth: number,
  viewportHeight: number,
): MenuPosition {
  const maxLeft = Math.max(EDGE, viewportWidth - width - EDGE);
  if (placement === "right") {
    // beside a trigger at the bottom of a rail: grow upwards from its bottom edge
    return {
      left: Math.min(trigger.right + GAP, maxLeft),
      bottom: Math.max(EDGE, viewportHeight - trigger.bottom),
    };
  }
  return { top: trigger.bottom + GAP, left: Math.min(Math.max(trigger.left, EDGE), maxLeft) };
}

/** "Jane Doe" → "JD"; falls back to the username or email. */
export function initialsOf(fullName: string | null, username: string | null, email: string): string {
  const words = (fullName ?? "").trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
  const source = words[0] ?? username ?? email.replace(/^@/, "");
  return (source.slice(0, 2) || "?").toUpperCase();
}

/** Roving focus over `count` items, wrapping at both ends. */
export function nextIndex(current: number, count: number, move: "next" | "prev" | "first" | "last"): number {
  if (count === 0) return -1;
  if (move === "first") return 0;
  if (move === "last") return count - 1;
  if (current < 0) return move === "next" ? 0 : count - 1;
  return (current + (move === "next" ? 1 : -1) + count) % count;
}
