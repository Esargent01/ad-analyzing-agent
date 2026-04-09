/**
 * Display formatters mirroring the Jinja filters in `src/reports/email.py`.
 *
 * The backend currently emits Decimal values as JSON strings (Pydantic v2
 * default), so every helper coerces through `Number()` before formatting.
 * If we later switch the backend to emit floats, these still work.
 */

type Numeric = number | string | null | undefined;

function toNumber(value: Numeric): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
}

/** $1,234 for >= 1000, $12.34 otherwise — matches `_format_currency`. */
export function formatCurrency(value: Numeric): string {
  const n = toNumber(value);
  if (Math.abs(n) >= 1000) {
    return `$${n.toLocaleString("en-US", {
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    })}`;
  }
  return `$${n.toFixed(2)}`;
}

/** 1,234 — matches `_format_intcomma`. */
export function formatIntComma(value: Numeric): string {
  const n = Math.round(toNumber(value));
  return n.toLocaleString("en-US");
}

/** 1.2 — matches `_format_one_decimal`. */
export function formatOneDecimal(value: Numeric): string {
  return toNumber(value).toFixed(1);
}

/**
 * 12.3% — matches `_format_pct`.
 *
 * Accepts either a 0-1 fraction (0.12 → "12.3%") or a pre-multiplied
 * percentage (12.3 → "12.3%"). The heuristic is the same as the Python
 * side: values < 1 are treated as fractions.
 */
export function formatPct(value: Numeric): string {
  const n = toNumber(value);
  const pct = n < 1 ? n * 100 : n;
  return `${pct.toFixed(1)}%`;
}

/** +12% / -4% / +0% — matches `_format_signed_pct`. */
export function formatSignedPct(value: Numeric): string {
  const n = toNumber(value);
  const pct = Math.round(n * 100);
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct}%`;
}

/** Short, human-friendly date label like "Apr 9, 2026". */
export function formatDateLabel(iso: string): string {
  const [year, month, day] = iso.split("-").map((s) => Number(s));
  if (!year || !month || !day) return iso;
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
