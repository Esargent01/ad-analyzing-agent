import {
  MediaBadge,
  StatusPill,
  type StatusKind,
} from "@/components/dashboard/primitives";
import type { VariantReport, VariantSummary } from "@/lib/api/types";
import {
  formatCurrency,
  formatIntComma,
  formatOneDecimal,
  formatPct,
} from "@/lib/format";

/**
 * Variant leaderboard tables used inside daily / weekly reports.
 *
 * Ported to the warm-editorial design system (Geist Mono for all
 * numerics, warm paper row striping, dashboard-primitive status
 * pills + media badges). Layout matches the design drop at
 * ``kleiber-agent-deign/project/src/dashboard/screens-{a,b}.jsx``:
 * a compact mono-font grid with an uppercase mono header row, tight
 * row padding, hover-lift on each row.
 *
 * Two shapes — the daily table renders a slim 7-column grid
 * (variant · media · hook · ctr · cpa · roas · status); the
 * weekly table adds hold, spend, purchases.
 */

const VARIANT_STATUSES = new Set<StatusKind>([
  "winner",
  "active",
  "steady",
  "new",
  "fatigue",
  "paused",
  "draft",
  "danger",
]);

function toStatusKind(status: string): StatusKind {
  const s = status.toLowerCase();
  return VARIANT_STATUSES.has(s as StatusKind) ? (s as StatusKind) : "steady";
}

// ---------------------------------------------------------------------------
// Daily table
// ---------------------------------------------------------------------------

const DAILY_COLS = "90px 48px 70px 70px 70px 70px 90px";

export function DailyVariantTable({ variants }: { variants: VariantReport[] }) {
  if (variants.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        No other active variants today.
      </p>
    );
  }

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
        background: "white",
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: DAILY_COLS,
          padding: "10px 16px",
          background: "var(--paper-2)",
          borderBottom: "1px solid var(--border)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--muted)",
          gap: 8,
        }}
      >
        <span>VARIANT</span>
        <span>TYPE</span>
        <span>HOOK</span>
        <span>CTR</span>
        <span>CPA</span>
        <span>ROAS</span>
        <span>STATUS</span>
      </div>
      {variants.map((v, i) => (
        <div
          key={v.variant_id}
          style={{
            display: "grid",
            gridTemplateColumns: DAILY_COLS,
            padding: "12px 16px",
            alignItems: "center",
            borderBottom:
              i < variants.length - 1
                ? "1px solid var(--border-soft)"
                : "none",
            fontFamily: "var(--font-mono)",
            fontSize: 12.5,
            gap: 8,
          }}
        >
          <span style={{ fontWeight: 500, color: "var(--ink)" }}>
            {v.variant_code}
          </span>
          <MediaBadge type={v.media_type} />
          <span style={{ color: "var(--ink-2)" }}>
            {v.media_type === "image" || v.hook_rate_pct == null
              ? "—"
              : `${v.hook_rate_pct.toFixed(1)}%`}
          </span>
          <span style={{ color: "var(--ink-2)" }}>
            {v.ctr_pct != null ? `${v.ctr_pct.toFixed(1)}%` : "—"}
          </span>
          <span style={{ color: "var(--ink-2)" }}>
            {v.cost_per_purchase != null && v.cost_per_purchase !== ""
              ? formatCurrency(v.cost_per_purchase)
              : "—"}
          </span>
          <span
            style={{
              color:
                v.roas != null && v.roas !== "" ? "oklch(40% 0.14 145)" : "var(--ink-2)",
            }}
          >
            {v.roas != null && v.roas !== ""
              ? `${formatOneDecimal(v.roas)}x`
              : "—"}
          </span>
          <span>
            <StatusPill kind={toStatusKind(v.status)}>{v.status}</StatusPill>
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Weekly table — two extra columns (hold, spend, purchases)
// ---------------------------------------------------------------------------

const WEEKLY_COLS = "80px 48px 70px 70px 70px 80px 70px 90px 70px";

export function WeeklyVariantTable({
  variants,
}: {
  variants: VariantSummary[];
}) {
  if (variants.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        No variants recorded for this week yet.
      </p>
    );
  }

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
        background: "white",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: WEEKLY_COLS,
          padding: "10px 16px",
          background: "var(--paper-2)",
          borderBottom: "1px solid var(--border)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--muted)",
          gap: 8,
        }}
      >
        <span>CODE</span>
        <span>TYPE</span>
        <span>HOOK</span>
        <span>HOLD</span>
        <span>CTR</span>
        <span>CPA</span>
        <span>ROAS</span>
        <span>SPEND</span>
        <span>PURCH</span>
      </div>
      {variants.map((v, i) => (
        <div
          key={v.variant_id}
          style={{
            display: "grid",
            gridTemplateColumns: WEEKLY_COLS,
            padding: "12px 16px",
            alignItems: "center",
            borderBottom:
              i < variants.length - 1
                ? "1px solid var(--border-soft)"
                : "none",
            fontFamily: "var(--font-mono)",
            fontSize: 12.5,
            gap: 8,
          }}
        >
          <span style={{ fontWeight: 500, color: "var(--ink)" }}>
            {v.variant_code}
          </span>
          <MediaBadge type={v.media_type} />
          <span style={{ color: "var(--ink-2)" }}>
            {v.media_type === "image" ? "—" : formatPct(v.hook_rate)}
          </span>
          <span style={{ color: "var(--ink-2)" }}>
            {v.media_type === "image" ? "—" : formatPct(v.hold_rate)}
          </span>
          <span style={{ color: "var(--ink-2)" }}>{formatPct(v.ctr)}</span>
          <span style={{ color: "var(--ink-2)" }}>
            {v.cost_per_purchase != null && v.cost_per_purchase !== ""
              ? formatCurrency(v.cost_per_purchase)
              : "—"}
          </span>
          <span
            style={{
              color:
                v.roas != null && v.roas !== ""
                  ? "oklch(40% 0.14 145)"
                  : "var(--ink-2)",
            }}
          >
            {v.roas != null && v.roas !== ""
              ? `${formatOneDecimal(v.roas)}x`
              : "—"}
          </span>
          <span style={{ color: "var(--ink-2)" }}>
            {formatCurrency(v.spend)}
          </span>
          <span style={{ color: "var(--ink-2)" }}>
            {formatIntComma(v.purchases)}
          </span>
        </div>
      ))}
    </div>
  );
}
