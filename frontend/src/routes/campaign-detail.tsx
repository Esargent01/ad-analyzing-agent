import { Link, Navigate, useParams } from "react-router-dom";

import { MetricCard } from "@/components/MetricCard";
import { StatusPill } from "@/components/StatusPill";
import { Card, CardContent } from "@/components/ui/Card";
import {
  useDailyDates,
  useExperiments,
  useMe,
  useWeeklyIndex,
} from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Campaign overview page — the landing surface once a user clicks a
 * campaign tile on /dashboard. Pulls four queries in parallel via
 * TanStack Query: /api/me (for campaign name), daily index, weekly
 * index, and experiments (for the pending-approvals count).
 *
 * Phase 4 scope: status tiles + quick-link cards. Phase 5 wires the
 * "latest report" links into actual detail pages.
 */
export function CampaignDetailRoute() {
  const { campaignId = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const daily = useDailyDates(campaignId);
  const weekly = useWeeklyIndex(campaignId);
  const experiments = useExperiments(campaignId);

  // 404-equivalent: authed user, but campaign isn't in their list.
  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const dailyCount = daily.data?.dates.length ?? 0;
  const weeklyCount = weekly.data?.weeks.length ?? 0;
  const pendingCount = experiments.data?.proposed_variants.length ?? 0;
  const latestDaily = daily.data?.dates[0];
  const latestWeek = weekly.data?.weeks[0];

  return (
    <div>
      <div className="mb-6">
        <Link
          to="/dashboard"
          className="text-xs text-[var(--accent)] no-underline hover:underline"
        >
          ← All campaigns
        </Link>
        <div className="mt-3 flex items-center gap-3">
          <h1 className="text-xl font-medium">
            {campaign?.name ?? "Campaign"}
          </h1>
          {campaign ? (
            <StatusPill kind={campaign.is_active ? "active" : "paused"}>
              {campaign.is_active ? "Active" : "Paused"}
            </StatusPill>
          ) : null}
        </div>
        <p className="mt-1 text-[11px] text-[var(--text-tertiary)]">
          ID: <span className="font-mono">{campaignId}</span>
        </p>
      </div>

      {/* Status tiles */}
      <div className="mb-8 grid gap-2 sm:grid-cols-3">
        <MetricCard
          label="Daily reports"
          value={daily.isLoading ? "—" : dailyCount}
          caption={
            latestDaily
              ? `latest ${formatDateLabel(latestDaily)}`
              : "no reports yet"
          }
        />
        <MetricCard
          label="Weekly reports"
          value={weekly.isLoading ? "—" : weeklyCount}
          caption={
            latestWeek ? `latest ${latestWeek.label}` : "no reports yet"
          }
        />
        <MetricCard
          label="Pending approvals"
          value={experiments.isLoading ? "—" : pendingCount}
          tone={pendingCount > 0 ? "up" : "flat"}
          caption={
            pendingCount > 0
              ? "waiting on you"
              : "nothing to review"
          }
        />
      </div>

      {/* Quick links */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to={`/campaigns/${campaignId}/reports/daily`}
          className="no-underline hover:no-underline"
        >
          <Card className="h-full transition-colors hover:border-[var(--accent)]">
            <h2 className="text-[15px] font-medium text-[var(--text)]">
              Daily reports
            </h2>
            <CardContent className="mt-2 text-[var(--text-secondary)]">
              Browse every daily snapshot with funnel, spotlight variant, and
              day-over-day diagnostics.
            </CardContent>
            <p className="mt-3 text-xs text-[var(--accent)]">
              View {dailyCount} report{dailyCount === 1 ? "" : "s"} →
            </p>
          </Card>
        </Link>

        <Link
          to={`/campaigns/${campaignId}/reports/weekly`}
          className="no-underline hover:no-underline"
        >
          <Card className="h-full transition-colors hover:border-[var(--accent)]">
            <h2 className="text-[15px] font-medium text-[var(--text)]">
              Weekly reports
            </h2>
            <CardContent className="mt-2 text-[var(--text-secondary)]">
              Full weekly breakdown with variant leaderboard, element
              rankings, and interaction effects.
            </CardContent>
            <p className="mt-3 text-xs text-[var(--accent)]">
              View {weeklyCount} week{weeklyCount === 1 ? "" : "s"} →
            </p>
          </Card>
        </Link>

        <Link
          to={`/campaigns/${campaignId}/experiments`}
          className="sm:col-span-2 no-underline hover:no-underline"
        >
          <Card className="h-full transition-colors hover:border-[var(--accent)]">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-[15px] font-medium text-[var(--text)]">
                  Next week&apos;s experiments
                </h2>
                <CardContent className="mt-2 text-[var(--text-secondary)]">
                  Review proposed variants, approve or reject them, and
                  suggest new gene pool entries.
                </CardContent>
              </div>
              {pendingCount > 0 ? (
                <StatusPill kind="new">
                  {pendingCount} pending
                </StatusPill>
              ) : null}
            </div>
            <p className="mt-3 text-xs text-[var(--accent)]">Open experiments →</p>
          </Card>
        </Link>
      </div>
    </div>
  );
}
