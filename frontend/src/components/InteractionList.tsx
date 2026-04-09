import type { InteractionInsight } from "@/lib/api/types";
import { formatPct, formatSignedPct } from "@/lib/format";

interface InteractionListProps {
  interactions: InteractionInsight[];
  limit?: number;
}

/**
 * Mirrors the weekly report's "Top element interactions" section.
 * Each row shows the element pair, the combined CTR + variant count,
 * and the interaction lift (green if positive, red if negative).
 */
export function InteractionList({
  interactions,
  limit = 5,
}: InteractionListProps) {
  if (interactions.length === 0) {
    return (
      <p className="text-xs text-[var(--text-tertiary)]">
        No pairwise interactions yet — need at least one variant that
        shares elements with another.
      </p>
    );
  }

  const rows = interactions.slice(0, limit);

  return (
    <div className="divide-y divide-[var(--border)] border-y border-[var(--border)]">
      {rows.map((i, idx) => {
        const lift = i.interaction_lift != null ? Number(i.interaction_lift) : null;
        const liftClass =
          lift != null
            ? lift > 0
              ? "text-[var(--green)]"
              : "text-[var(--red)]"
            : "text-[var(--text-tertiary)]";
        return (
          <div
            key={`${i.slot_a_name}-${i.slot_a_value}-${i.slot_b_name}-${i.slot_b_value}-${idx}`}
            className="flex flex-col gap-1 py-2 text-xs sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0 flex-1">
              <span className="font-medium">{i.slot_a_name}</span>:{" "}
              {truncate(i.slot_a_value, 25)}
              <span className="mx-1 text-[var(--text-tertiary)]">+</span>
              <span className="font-medium">{i.slot_b_name}</span>:{" "}
              {truncate(i.slot_b_value, 25)}
            </div>
            <div className="flex items-baseline gap-3">
              <span className={`font-medium ${liftClass}`}>
                {lift != null ? formatSignedPct(lift) : "—"}
              </span>
              <span className="text-[11px] text-[var(--text-tertiary)]">
                {formatPct(i.combined_avg_ctr)} CTR · {i.variants_tested}{" "}
                variant{i.variants_tested === 1 ? "" : "s"}
              </span>
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
