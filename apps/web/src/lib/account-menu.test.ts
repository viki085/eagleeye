import { describe, expect, it } from "vitest";

import { initialsOf, menuPosition, nextIndex } from "./account-menu";

const rect = (left: number, top: number, size = 28) => ({ left, top, right: left + size, bottom: top + size });

describe("menuPosition", () => {
  it("opens below the trigger, aligned to its left edge", () => {
    expect(menuPosition(rect(100, 10), "below", 288, 1400, 900)).toEqual({ top: 46, left: 100 });
  });

  it("stays inside the viewport when the trigger is at the right edge", () => {
    expect(menuPosition(rect(1360, 10), "below", 288, 1400, 900).left).toBe(1400 - 288 - 8);
  });

  it("opens beside a rail trigger and grows upwards from its bottom", () => {
    expect(menuPosition(rect(10, 850), "right", 288, 1400, 900)).toEqual({ left: 46, bottom: 22 });
  });

  it("never places the panel off the left edge on a narrow screen", () => {
    expect(menuPosition(rect(0, 10), "below", 288, 300, 600).left).toBe(8);
  });
});

describe("initialsOf", () => {
  it.each([
    ["Jane Doe", null, "", "JD"],
    ["Jane van der Berg", null, "", "JB"],
    ["Cher", null, "", "CH"],
    [null, "eagle_admin", "", "EA"],
    [null, null, "@sam", "SA"],
    [null, null, "", "?"],
  ])("%s / %s / %s → %s", (name, username, email, expected) => {
    expect(initialsOf(name, username, email)).toBe(expected);
  });
});

describe("nextIndex", () => {
  it("wraps in both directions", () => {
    expect(nextIndex(1, 2, "next")).toBe(0);
    expect(nextIndex(0, 2, "prev")).toBe(1);
  });

  it("starts from the ends when nothing is focused", () => {
    expect(nextIndex(-1, 3, "next")).toBe(0);
    expect(nextIndex(-1, 3, "prev")).toBe(2);
    expect(nextIndex(1, 3, "last")).toBe(2);
    expect(nextIndex(2, 3, "first")).toBe(0);
  });

  it("returns -1 with no items", () => {
    expect(nextIndex(0, 0, "next")).toBe(-1);
  });
});
