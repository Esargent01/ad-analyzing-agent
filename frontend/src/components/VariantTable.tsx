import {
  MediaBadge,
  StatusPill,
  type StatusKind,
} from "@/components/dashboard/primitives";
import type {
  VariantReport,
  VariantSummary,
  VariantTableColumn,
} from "@/lib/api/types";
import {
  formatCurrency,
  formatIntComma,
  formatOneDecimal,
} from "@/lib/format";

/** Stringify one VariantReport/VariantSummary field based on the
 *  VariantTableColumn spec shipped by the server. Mirrors the Jinja
 *  ``format_cell`` macro in ``src/reports/templates/daily_email.html``
 *  so email + dashboard render the same text. */
function formatColumnValue<T extends Record<string, unknown>>(
  row: T,
  col: VariantTableColumn,
  mediaType: string,
): string {
  const raw = row[col.key as keyof T];

  if (col.image_em_dash && (mediaType || "").toLowerCase() === "image") {
    return "—";
  }
  if (raw == null || raw === "") return "—";

  switch (col.fmt) {
    case "currency":
      return formatCurrency(raw as string | number);
    case "int_comma":
    case "int":
      return formatIntComma(raw as string | number);
    case "pct": {
      const n = typeof raw === "number" ? raw : Number(raw);
      return Number.isFinite(n) ? `${n.toFixed(1)}%` : "—";
    }
    case "roas": {
      const n = typeof raw === "number" ? raw : Number(raw);
      return !n ? "—" : `${formatOneDecimal(n)}x`;
    }
    case "onedecimal":
      return formatOneDecimal(raw as string | number);
    default:
      return String(raw);
  }
}

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

/** Default column spec (Sales) used when the caller doesn't supply
 *  one — keeps existing callers of ``DailyVariantTable`` working. */
const DEFAULT_DAILY_COLUMNS: VariantTableColumn[] = [
  { label: "HOOK", key: "hook_rate_pct", fmt: "pct", image_em_dash: true },
  { label: "CTR", key: "ctr_pct", fmt: "pct", image_em_dash: false },
  { label: "CPA", key: "cost_per_purchase", fmt: "currency", image_em_dash: false },
  { label: "ROAS", key: "roas", fmt: "roas", image_em_dash: false },
];

export function DailyVariantTable({
  variants,
  columns,
}: {
  variants: VariantReport[];
  columns?: VariantTableColumn[];
}) {
  const cols = columns && columns.length > 0 ? columns : DEFAULT_DAILY_COLUMNS;

  // ``VARIANT``, ``TYPE``, N middle columns, ``STATUS``.
  const gridTemplate =
    `90px 48px ${cols.map(() => "72px").join(" ")} 90px`;

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
          gridTemplateColumns: gridTemplate,
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
        {cols.map((col) => (
          <span key={col.label}>{col.label}</span>
        ))}
        <span>STATUS</span>
      </div>
      {variants.map((v, i) => (
        <div
          key={v.variant_id}
          style={{
            display: "grid",
            gridTemplateColumns: gridTemplate,
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
          {cols.map((col) => {
            const cell = formatColumnValue(
              v as unknown as Record<string, unknown>,
              col,
              v.media_type,
            );
            // Tint the value green only for the ROAS column when
            // it's populated — preserves the current Sales visual
            // cue without needing per-column tone metadata.
            const greenTint = col.key === "roas" && cell !== "—";
            return (
              <span
                key={col.label}
                style={{
                  color: greenTint ? "oklch(40% 0.14 145)" : "var(--ink-2)",
                }}
              >
                {cell}
              </span>
            );
          })}
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

/** Sales-flavoured weekly default (matches the legacy fixed layout:
 *  HOOK · HOLD · CTR · CPA · ROAS · SPEND · PURCH). Used when the
 *  caller doesn't pass objective-keyed ``columns``. */
const DEFAULT_WEEKLY_COLUMNS: VariantTableColumn[] = [
  { label: "HOOK", key: "hook_rate_pct", fmt: "pct", image_em_dash: true },
  { label: "HOLD", key: "hold_rate_pct", fmt: "pct", image_em_dash: true },
  { label: "CTR", key: "ctr_pct", fmt: "pct", image_em_dash: false },
  { label: "CPA", key: "cost_per_purchase", fmt: "currency", image_em_dash: false },
  { label: "ROAS", key: "roas", fmt: "roas", image_em_dash: false },
  { label: "SPEND", key: "spend", fmt: "currency", image_em_dash: false },
  { label: "PURCH", key: "purchases", fmt: "int_comma", image_em_dash: false },
];

export function WeeklyVariantTable({
  variants,
  columns,
}: {
  variants: VariantSummary[];
  columns?: VariantTableColumn[];
}) {
  // When the caller passes objective-keyed columns, slot them in
  // between CODE/TYPE and SPEND/PURCH. The profile's
  // ``variant_col_specs`` is tuned for the daily (4 cols); weekly
  // traditionally tacks SPEND + PURCH on the end. To keep the weekly
  // table as useful for non-Sales as it is for Sales, we append the
  // same SPEND + PURCH columns regardless of objective when a
  // custom column set is provided.
  const middleCols = columns && columns.length > 0 ? columns : DEFAULT_WEEKLY_COLUMNS;
  const cols =
    columns && columns.length > 0
      ? [
          ...middleCols,
          {
            label: "SPEND",
            key: "spend",
            fmt: "currency",
            image_em_dash: false,
          } as VariantTableColumn,
        ]
      : middleCols;
  const gridTemplate =
    `80px 48px ${cols.map(() => "72px").join(" ")}`;

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
          gridTemplateColumns: gridTemplate,
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
        {cols.map((col) => (
          <span key={col.label}>{col.label}</span>
        ))}
      </div>
      {variants.map((v, i) => (
        <div
          key={v.variant_id}
          style={{
            display: "grid",
            gridTemplateColumns: gridTemplate,
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
          {cols.map((col) => {
            const cell = formatColumnValue(
              v as unknown as Record<string, unknown>,
              col,
              v.media_type,
            );
            const greenTint = col.key === "roas" && cell !== "—";
            return (
              <span
                key={col.label}
                style={{
                  color: greenTint ? "oklch(40% 0.14 145)" : "var(--ink-2)",
                }}
              >
                {cell}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}
