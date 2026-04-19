import type { StatusKind } from "@/components/StatusPill";
import { StatusPill } from "@/components/StatusPill";
import type { VariantReport, VariantSummary } from "@/lib/api/types";
import {
  formatCurrency,
  formatIntComma,
  formatOneDecimal,
  formatPct,
} from "@/lib/format";

const VARIANT_STATUSES = new Set<StatusKind>([
  "winner",
  "steady",
  "new",
  "fatigue",
  "paused",
]);

function toStatusKind(status: string): StatusKind {
  const s = status.toLowerCase();
  return VARIANT_STATUSES.has(s as StatusKind)
    ? (s as StatusKind)
    : "steady";
}

// ---------------------------------------------------------------------------
// Daily: reduced set of columns (Variant / Hook / CTR / CPA / ROAS / Status)
// ---------------------------------------------------------------------------

export function DailyVariantTable({ variants }: { variants: VariantReport[] }) {
  if (variants.length === 0) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        No other active variants today.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-[var(--border)] text-[10px] uppercase tracking-[0.4px] text-[var(--text-tertiary)]">
            <th className="p-2 text-left font-medium">Variant</th>
            <th className="p-2 text-left font-medium">Hook</th>
            <th className="p-2 text-left font-medium">CTR</th>
            <th className="p-2 text-left font-medium">CPA</th>
            <th className="p-2 text-left font-medium">ROAS</th>
            <th className="p-2 text-left font-medium">Status</th>
          </tr>
        </thead>
        <tbody>
          {variants.map((v) => (
            <tr
              key={v.variant_id}
              className="border-b border-[var(--border)]"
            >
              <td className="p-2 font-mono text-[11px] text-[var(--text)]">
                {v.variant_code}
              </td>
              {/* Image variants have no meaningful hook rate — em-dash
                  instead of a misleading 0.0%. Same treatment the
                  email templates use. */}
              <td className="p-2">
                {v.media_type === "image" || v.hook_rate_pct == null
                  ? "—"
                  : `${v.hook_rate_pct.toFixed(1)}%`}
              </td>
              <td className="p-2">
                {v.ctr_pct != null ? `${v.ctr_pct.toFixed(1)}%` : "—"}
              </td>
              <td className="p-2">
                {v.cost_per_purchase != null && v.cost_per_purchase !== ""
                  ? formatCurrency(v.cost_per_purchase)
                  : "—"}
              </td>
              <td className="p-2">
                {v.roas != null && v.roas !== ""
                  ? `${formatOneDecimal(v.roas)}x`
                  : "—"}
              </td>
              <td className="p-2">
                <StatusPill kind={toStatusKind(v.status)}>{v.status}</StatusPill>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Weekly: full column set (adds Hold / Spend / Purchases)
// ---------------------------------------------------------------------------

export function WeeklyVariantTable({
  variants,
}: {
  variants: VariantSummary[];
}) {
  if (variants.length === 0) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        No variants recorded for this week yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr className="border-b border-[var(--border)] text-[10px] uppercase tracking-[0.4px] text-[var(--text-tertiary)]">
            <th className="p-2 text-left font-medium">Variant</th>
            <th className="p-2 text-left font-medium">Status</th>
            <th className="p-2 text-left font-medium">Hook</th>
            <th className="p-2 text-left font-medium">Hold</th>
            <th className="p-2 text-left font-medium">CTR</th>
            <th className="p-2 text-left font-medium">CPA</th>
            <th className="p-2 text-left font-medium">ROAS</th>
            <th className="p-2 text-left font-medium">Spend</th>
            <th className="p-2 text-left font-medium">Purch.</th>
          </tr>
        </thead>
        <tbody>
          {variants.map((v) => (
            <tr
              key={v.variant_id}
              className="border-b border-[var(--border)]"
            >
              <td className="p-2 font-mono text-[11px] text-[var(--text)]">
                {v.variant_code}
              </td>
              <td className="p-2">
                <StatusPill kind={toStatusKind(v.status)}>{v.status}</StatusPill>
              </td>
              <td className="p-2">
                {v.media_type === "image" ? "—" : formatPct(v.hook_rate)}
              </td>
              <td className="p-2">
                {v.media_type === "image" ? "—" : formatPct(v.hold_rate)}
              </td>
              <td className="p-2">{formatPct(v.ctr)}</td>
              <td className="p-2">
                {v.cost_per_purchase != null && v.cost_per_purchase !== ""
                  ? formatCurrency(v.cost_per_purchase)
                  : "—"}
              </td>
              <td className="p-2">
                {v.roas != null && v.roas !== ""
                  ? `${formatOneDecimal(v.roas)}x`
                  : "—"}
              </td>
              <td className="p-2">{formatCurrency(v.spend)}</td>
              <td className="p-2">{formatIntComma(v.purchases)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
