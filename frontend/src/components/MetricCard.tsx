import type { ReactNode } from "react";

type Tone = "neutral" | "up" | "down" | "flat";

export interface MetricCardProps {
  label: string;
  value: ReactNode;
  trend?: ReactNode;
  tone?: Tone;
  /** Small caption shown under the value (e.g., "last 7 days"). */
  caption?: ReactNode;
  className?: string;
}

/**
 * Single topline metric tile.
 *
 * Visually aligned with the dashboard primitives' ``StatTile`` — warm
 * paper palette, mono numerics, label in eyebrow treatment. Used
 * across campaign overview + daily / weekly report details.
 *
 * Exposes ``trend`` + ``tone`` for day-over-day deltas; the old
 * ``caption`` slot still works for "last 7 days" labels.
 */
export function MetricCard({
  label,
  value,
  trend,
  tone = "neutral",
  caption,
}: MetricCardProps) {
  const trendColor =
    tone === "up"
      ? "oklch(40% 0.14 145)"
      : tone === "down"
        ? "oklch(48% 0.16 28)"
        : "var(--muted)";
  return (
    <div
      style={{
        padding: 16,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--muted)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 500,
          letterSpacing: "-0.025em",
          marginTop: 4,
          color: "var(--ink)",
        }}
      >
        {value}
      </div>
      {trend ? (
        <div
          style={{
            marginTop: 3,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: trendColor,
          }}
        >
          {trend}
        </div>
      ) : null}
      {caption ? (
        <div
          style={{
            marginTop: 3,
            fontSize: 12,
            color: "var(--muted)",
          }}
        >
          {caption}
        </div>
      ) : null}
    </div>
  );
}
