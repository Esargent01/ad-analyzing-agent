import { Link, useParams } from "react-router-dom";

import { Card, CardContent } from "@/components/ui/Card";
import { formatDateLabel } from "@/lib/format";

/**
 * Placeholder for the daily + weekly report detail pages. Phase 5 swaps
 * this out for funnel charts, variant leaderboards, element rankings,
 * and the best-variant spotlight. For now it just confirms scoping and
 * links back to the list page.
 */
export function DailyReportDetailStub() {
  const { campaignId = "", reportDate = "" } = useParams();
  return (
    <DetailStub
      title={`Daily report · ${formatDateLabel(reportDate)}`}
      backLabel="← Daily reports"
      backTo={`/campaigns/${campaignId}/reports/daily`}
      subtitle={reportDate}
    />
  );
}

export function WeeklyReportDetailStub() {
  const { campaignId = "", weekStart = "" } = useParams();
  return (
    <DetailStub
      title={`Weekly report · week of ${formatDateLabel(weekStart)}`}
      backLabel="← Weekly reports"
      backTo={`/campaigns/${campaignId}/reports/weekly`}
      subtitle={`week_start = ${weekStart}`}
    />
  );
}

interface DetailStubProps {
  title: string;
  subtitle: string;
  backLabel: string;
  backTo: string;
}

function DetailStub({ title, subtitle, backLabel, backTo }: DetailStubProps) {
  return (
    <div>
      <div className="mb-6">
        <Link
          to={backTo}
          className="text-xs text-[var(--accent)] no-underline hover:underline"
        >
          {backLabel}
        </Link>
        <h1 className="mt-3 text-xl font-medium">{title}</h1>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
          {subtitle}
        </p>
      </div>
      <Card>
        <CardContent className="text-[var(--text-secondary)]">
          <p>
            The detail view (funnel, variant leaderboard, element rankings,
            and best-variant spotlight) lands in Phase 5. For now, the data
            is available via the API and the existing static HTML reports.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
