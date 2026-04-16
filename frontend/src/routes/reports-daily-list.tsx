import { Link, Navigate, useParams } from "react-router-dom";

import { Card, CardContent } from "@/components/ui/Card";
import { Skeleton, SkeletonListRow } from "@/components/ui/Skeleton";
import { useDailyDates, useMe } from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Daily reports index — one row per report date. Phase 4 scope: the
 * rows render, but the destination detail page is a Phase 5 stub until
 * the heavy report-detail components land.
 */
export function ReportsDailyListRoute() {
  const { campaignId = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const dates = useDailyDates(campaignId);

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
        <h1 className="mt-3 text-xl font-medium">Daily reports</h1>
        {dates.isLoading ? (
          <Skeleton className="mt-2 h-3 w-40" />
        ) : (
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {dates.data?.dates.length
              ? `${dates.data.dates.length} report${dates.data.dates.length === 1 ? "" : "s"}, newest first`
              : "No daily reports yet. Run the cycle cron and they'll appear here."}
          </p>
        )}
      </div>

      {dates.isError ? (
        <Card>
          <CardContent className="text-[var(--red)]">
            Couldn&apos;t load daily reports. Try refreshing.
          </CardContent>
        </Card>
      ) : null}

      {dates.isLoading ? (
        <div className="overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4">
          {Array.from({ length: 5 }).map((_, i) => (
            <SkeletonListRow key={i} />
          ))}
        </div>
      ) : null}

      {dates.data?.dates.length ? (
        <div className="divide-y divide-[var(--border)] overflow-hidden rounded-lg border border-[var(--border)]">
          {dates.data.dates.map((iso) => (
            <Link
              key={iso}
              to={`/campaigns/${campaignId}/reports/daily/${iso}`}
              className="flex items-center justify-between bg-[var(--bg)] px-4 py-3 no-underline transition-colors hover:bg-[var(--bg-secondary)] hover:no-underline"
            >
              <span className="text-sm text-[var(--text)]">
                {formatDateLabel(iso)}
              </span>
              <span className="text-xs text-[var(--text-tertiary)]">
                {iso} →
              </span>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
