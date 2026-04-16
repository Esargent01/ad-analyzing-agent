import { Link, Navigate, useParams } from "react-router-dom";

import { Card, CardContent } from "@/components/ui/Card";
import { Skeleton, SkeletonListRow } from "@/components/ui/Skeleton";
import { useMe, useWeeklyIndex } from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Weekly reports index — one row per week, using the pre-computed
 * `label` from the backend (e.g., "Mar 30 - Apr 5") so date ranges
 * read nicely without extra client math. URL uses week_start as the
 * stable path key to sidestep ISO-week ambiguity.
 */
export function ReportsWeeklyListRoute() {
  const { campaignId = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const weeks = useWeeklyIndex(campaignId);

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div>
      <div className="mb-6">
        <Link
          to={`/campaigns/${campaignId}`}
          className="text-xs text-[var(--accent)] no-underline hover:underline"
        >
          ← {campaign?.name ?? "Campaign"}
        </Link>
        <h1 className="mt-3 text-xl font-medium">Weekly reports</h1>
        {weeks.isLoading ? (
          <Skeleton className="mt-2 h-3 w-40" />
        ) : (
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {weeks.data?.weeks.length
              ? `${weeks.data.weeks.length} week${weeks.data.weeks.length === 1 ? "" : "s"}, newest first`
              : "No weekly reports yet. They generate every Monday once the cycle has run for a full week."}
          </p>
        )}
      </div>

      {weeks.isError ? (
        <Card>
          <CardContent className="text-[var(--red)]">
            Couldn&apos;t load weekly reports. Try refreshing.
          </CardContent>
        </Card>
      ) : null}

      {weeks.isLoading ? (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonListRow key={i} />
          ))}
        </div>
      ) : null}

      {weeks.data?.weeks.length ? (
        <div className="divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)]">
          {weeks.data.weeks.map((week) => (
            <Link
              key={week.week_start}
              to={`/campaigns/${campaignId}/reports/weekly/${week.week_start}`}
              className="flex items-center justify-between bg-[var(--bg)] px-4 py-3 no-underline transition-colors hover:bg-[var(--bg-secondary)] hover:no-underline"
            >
              <div>
                <div className="text-sm text-[var(--text)]">{week.label}</div>
                <div className="mt-0.5 text-[11px] text-[var(--text-tertiary)]">
                  {formatDateLabel(week.week_start)} –{" "}
                  {formatDateLabel(week.week_end)}
                </div>
              </div>
              <span className="text-xs text-[var(--text-tertiary)]">
                {week.week_start} →
              </span>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
