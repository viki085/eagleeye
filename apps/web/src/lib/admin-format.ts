/** Number formatting for the admin console (tabular figures are applied in CSS). */

export function money(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  if (v !== 0 && Math.abs(v) < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function count(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toLocaleString("en-US");
}

export function seconds(v: number | null | undefined): string {
  if (v === null || v === undefined) return "n/a";
  return v < 10 ? `${v.toFixed(1)} s` : `${Math.round(v)} s`;
}

export function pct(part: number, whole: number): string {
  if (!whole) return "—";
  const value = (100 * part) / whole;
  return `${value < 10 && value > 0 ? value.toFixed(1) : Math.round(value)}%`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  const mins = Math.round((Date.now() - date.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function bucketLabel(iso: string, hourly: boolean): string {
  const d = new Date(iso);
  return hourly
    ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" })
    : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}
