/** Compact counts: 950 · 12.4K · 3.1M (one decimal, trailing .0 dropped). */
export function compactNumber(n: number): string {
  const abs = Math.abs(n);
  const units: [number, string][] = [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [size, suffix] of units) {
    if (abs >= size) {
      return `${(n / size).toFixed(1).replace(/\.0$/, "")}${suffix}`;
    }
  }
  return Math.round(n).toLocaleString("en-US");
}

/** Money: 4 decimals below $1 (LLM costs are tiny), 2 decimals above. */
export function money(usd: number): string {
  if (usd === 0) return "$0.00";
  if (Math.abs(usd) < 0.0001) return "<$0.0001";
  const digits = Math.abs(usd) < 1 ? 4 : 2;
  return `$${usd.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

/** Percent with precision that stays meaningful for tiny shares: 0.08% · 4.2% · 87%. */
export function percent(fraction: number): string {
  const p = fraction * 100;
  if (p === 0) return "0%";
  if (p < 0.01) return "<0.01%";
  if (p < 1) return `${p.toFixed(2)}%`;
  if (p < 10) return `${p.toFixed(1)}%`;
  return `${Math.round(p)}%`;
}

export type Severity = "normal" | "warning" | "critical";

export function quotaSeverity(fraction: number): Severity {
  if (fraction >= 0.95) return "critical";
  if (fraction >= 0.8) return "warning";
  return "normal";
}

/** "Wed 12 Nov" from an ISO date, read as a calendar date (no timezone shift). */
export function dayLabel(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const date = new Date(y, m - 1, d);
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}
