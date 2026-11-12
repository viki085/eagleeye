import { describe, expect, it } from "vitest";

import { compactNumber, dayLabel, money, percent, quotaSeverity } from "./format";

describe("format", () => {
  it("compacts counts", () => {
    expect(compactNumber(950)).toBe("950");
    expect(compactNumber(12_400)).toBe("12.4K");
    expect(compactNumber(3_000_000)).toBe("3M");
    expect(compactNumber(1_250_000_000)).toBe("1.3B");
  });

  it("formats money with precision that suits LLM costs", () => {
    expect(money(0)).toBe("$0.00");
    expect(money(0.004307)).toBe("$0.0043");
    expect(money(0.00001)).toBe("<$0.0001");
    expect(money(12.345)).toBe("$12.35");
    expect(money(499.5)).toBe("$499.50");
  });

  it("keeps tiny percentages visible", () => {
    expect(percent(0)).toBe("0%");
    expect(percent(0.0000086)).toBe("<0.01%");
    expect(percent(0.0008)).toBe("0.08%");
    expect(percent(0.042)).toBe("4.2%");
    expect(percent(0.87)).toBe("87%");
  });

  it("maps quota use to severity", () => {
    expect(quotaSeverity(0.5)).toBe("normal");
    expect(quotaSeverity(0.8)).toBe("warning");
    expect(quotaSeverity(0.95)).toBe("critical");
    expect(quotaSeverity(1.2)).toBe("critical");
  });

  it("labels ISO days without timezone drift", () => {
    expect(dayLabel("2026-11-12")).toBe("Thu 12 Nov");
  });
});
