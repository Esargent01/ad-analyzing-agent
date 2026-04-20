import type { InteractionInsight } from "@/lib/api/types";
import { formatPct, formatSignedPct } from "@/lib/format";

interface InteractionListProps {
  interactions: InteractionInsight[];
  limit?: number;
}

/**
 * Weekly report's "Top pairwise lifts" list.
 *
 * Ported to the warm-editorial palette — single white card, each row
 * compact and mono-flavored. Green lift for synergy, terracotta for
 * conflict. Matches the layout on the design drop
 * (``kleiber-agent-deign/project/src/dashboard/screens-b.jsx``).
 */
export function InteractionList({
  interactions,
  limit = 5,
}: InteractionListProps) {
  if (interactions.length === 0) {
    return (
      <p style={{ fontSize: 12, color: "var(--muted)" }}>
        No pairwise interactions yet — need at least one variant that shares
        elements with another.
      </p>
    );
  }

  const rows = interactions.slice(0, limit);

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
        overflow: "hidden",
      }}
    >
      {rows.map((i, idx) => {
        const lift = i.interaction_lift != null ? Number(i.interaction_lift) : null;
        const liftColor =
          lift != null
            ? lift > 0
              ? "oklch(40% 0.14 145)"
              : "oklch(48% 0.16 28)"
            : "var(--muted)";
        return (
          <div
            key={`${i.slot_a_name}-${i.slot_a_value}-${i.slot_b_name}-${i.slot_b_value}-${idx}`}
            style={{
              padding: "12px 16px",
              borderBottom:
                idx < rows.length - 1 ? "1px solid var(--border-soft)" : "none",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 10,
                flexWrap: "wrap",
              }}
            >
              <div
                style={{
                  fontSize: 12.5,
                  color: "var(--ink-2)",
                  minWidth: 0,
                  flex: 1,
                }}
              >
                <span style={{ color: "var(--muted)" }}>
                  {i.slot_a_name}
                </span>{" "}
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  {truncate(i.slot_a_value, 24)}
                </span>{" "}
                <span style={{ color: "var(--muted)" }}>×</span>{" "}
                <span style={{ color: "var(--muted)" }}>
                  {i.slot_b_name}
                </span>{" "}
                <span style={{ fontFamily: "var(--font-mono)" }}>
                  {truncate(i.slot_b_value, 24)}
                </span>
              </div>
              <span
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: 12.5,
                  fontWeight: 500,
                  color: liftColor,
                }}
              >
                {lift != null ? formatSignedPct(lift) : "—"}
              </span>
            </div>
            <div
              style={{
                marginTop: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 10.5,
                color: "var(--muted)",
              }}
            >
              {formatPct(i.combined_avg_ctr)} CTR · {i.variants_tested}{" "}
              variant{i.variants_tested === 1 ? "" : "s"}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1)}…`;
}
