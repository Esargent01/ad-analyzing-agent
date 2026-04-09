import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

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

const toneClasses: Record<Tone, string> = {
  neutral: "text-[var(--text-tertiary)]",
  up: "text-[var(--green)]",
  down: "text-[var(--red)]",
  flat: "text-[var(--text-tertiary)]",
};

/**
 * Single topline metric tile, matching the `.mc` card pattern from the
 * Jinja report templates (`src/reports/templates/components/base.html`).
 * Used on campaign overview + report detail pages.
 */
export function MetricCard({
  label,
  value,
  trend,
  tone = "neutral",
  caption,
  className,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded bg-[var(--bg-secondary)] px-4 py-3",
        className,
      )}
    >
      <div className="text-[11px] uppercase tracking-[0.3px] text-[var(--text-tertiary)]">
        {label}
      </div>
      <div className="mt-1 text-xl font-medium text-[var(--text)]">
        {value}
      </div>
      {trend ? (
        <div className={cn("mt-0.5 text-[11px]", toneClasses[tone])}>
          {trend}
        </div>
      ) : null}
      {caption ? (
        <div className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
          {caption}
        </div>
      ) : null}
    </div>
  );
}
