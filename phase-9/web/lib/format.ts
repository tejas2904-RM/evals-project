const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function pct(rate: number | null | undefined): string {
  return rate === null || rate === undefined ? "—" : `${Math.round(rate * 100)}%`;
}

export function usd(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  if (value > 0 && value < 0.01 && digits <= 2) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(digits)}`;
}

// Dates are formatted from the ISO string itself (UTC), so the output doesn't depend on the viewer's timezone.
export function shortDate(iso: string | null | undefined, withYear = false): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!m) return "—";
  const [, y, mo, d] = m;
  const text = `${Number(d)} ${MONTHS[Number(mo) - 1]}`;
  return withYear ? `${text} ${y}` : text;
}

export function plural(n: number, word: string, many = `${word}s`): string {
  return `${n} ${n === 1 ? word : many}`;
}

export function blockingRisks(counts: { critical: number; high: number }): string {
  const parts = [];
  if (counts.critical) parts.push(`${counts.critical} critical`);
  if (counts.high) parts.push(`${counts.high} high`);
  if (!parts.length) return "no high risks";
  const n = counts.critical + counts.high;
  return `${parts.join(", ")} risk${n === 1 ? "" : "s"}`;
}

export function joinList(items: string[]): string {
  return items.join(" + ");
}
