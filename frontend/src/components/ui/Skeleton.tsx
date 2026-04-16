import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/**
 * Base skeleton primitive — a pulsing cream-tinted rectangle. Size it
 * with Tailwind utilities so the placeholder matches the real content's
 * box and there's no layout shift when data arrives.
 *
 * ```tsx
 * <Skeleton className="h-4 w-40" />
 * ```
 */
export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded bg-[var(--bg-secondary)]",
        className,
      )}
      aria-hidden="true"
      {...props}
    />
  );
}

/**
 * Matches the `MetricCard` layout pixel-for-pixel (same padding + tile
 * background) so swapping a loaded MetricCard in doesn't jump the grid.
 * See `frontend/src/components/MetricCard.tsx`.
 */
export function SkeletonMetricCard() {
  return (
    <div className="rounded bg-[var(--bg-secondary)] px-4 py-3">
      <Skeleton className="h-3 w-16 bg-[var(--border)]" />
      <Skeleton className="mt-2 h-6 w-24 bg-[var(--border)]" />
    </div>
  );
}

/**
 * Row placeholder for the daily/weekly report index pages — two bars
 * aligned like "label" + "value", with the same bottom border rhythm as
 * the real list rows.
 */
export function SkeletonListRow() {
  return (
    <div className="flex items-center justify-between border-b border-[var(--border)] py-3 last:border-b-0">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-4 w-16" />
    </div>
  );
}

/**
 * Full-page placeholder for daily + weekly report detail routes. Renders
 * a 4-tile metric grid + a narrative card so the layout looks intentional
 * while the report payload is in flight.
 */
export function SkeletonReportBody() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonMetricCard key={i} />
        ))}
      </div>
      <div className="rounded-[var(--radius-lg)] border border-[var(--border)] bg-white p-5">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="mt-3 h-3 w-full" />
        <Skeleton className="mt-2 h-3 w-5/6" />
        <Skeleton className="mt-2 h-3 w-4/6" />
      </div>
    </div>
  );
}
