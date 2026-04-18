import { useState } from "react";
import { Link, Navigate, useNavigate, useParams } from "react-router-dom";

import { MetricCard } from "@/components/MetricCard";
import { StatusPill } from "@/components/StatusPill";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { SkeletonMetricCard } from "@/components/ui/Skeleton";
import {
  useDailyDates,
  useDeleteCampaign,
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
  const navigate = useNavigate();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const daily = useDailyDates(campaignId);
  const weekly = useWeeklyIndex(campaignId);
  const experiments = useExperiments(campaignId);
  const deleteCampaign = useDeleteCampaign();

  // Two-stage confirm: first click arms the button, second click fires
  // the DELETE. Guarded by a typed-in campaign name match so an
  // accidental double-tap can't nuke data — users have to type the
  // exact campaign name into the confirmation input.
  const [confirmArmed, setConfirmArmed] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const confirmMatches =
    !!campaign && confirmText.trim() === campaign.name;

  const handleDelete = async () => {
    if (!confirmMatches) return;
    try {
      await deleteCampaign.mutateAsync(campaignId);
      navigate("/dashboard", { replace: true });
    } catch {
      // Mutation state surfaces the error below; keep the user on the
      // page so they can retry or cancel.
    }
  };

  // 404-equivalent: authed user, but campaign isn't in their list.
  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const dailyCount = daily.data?.dates.length ?? 0;
  const weeklyCount = weekly.data?.weeks.length ?? 0;
  // Phase H: prefer the unified ``pending_approvals`` list so
  // pause_variant and scale_budget proposals are counted alongside
  // new variants. Fall back to the legacy ``proposed_variants`` field
  // for back-compat during rollout (pre-Phase-H backend).
  const pendingCount =
    experiments.data?.pending_approvals?.length ??
    experiments.data?.proposed_variants.length ??
    0;
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
        {daily.isLoading ? (
          <SkeletonMetricCard />
        ) : (
          <MetricCard
            label="Daily reports"
            value={dailyCount}
            caption={
              latestDaily
                ? `latest ${formatDateLabel(latestDaily)}`
                : "no reports yet"
            }
          />
        )}
        {weekly.isLoading ? (
          <SkeletonMetricCard />
        ) : (
          <MetricCard
            label="Weekly reports"
            value={weeklyCount}
            caption={
              latestWeek ? `latest ${latestWeek.label}` : "no reports yet"
            }
          />
        )}
        {experiments.isLoading ? (
          <SkeletonMetricCard />
        ) : (
          <MetricCard
            label="Pending approvals"
            value={pendingCount}
            tone={pendingCount > 0 ? "up" : "flat"}
            caption={
              pendingCount > 0 ? "waiting on you" : "nothing to review"
            }
          />
        )}
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

      {/* Danger zone — permanent delete. Hidden behind a two-stage
          confirm so an accidental click can't wipe a campaign. */}
      <div className="mt-10 rounded border border-red-900/40 bg-red-950/20 p-4">
        <h2 className="text-[13px] font-medium text-red-300">Danger zone</h2>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Delete this campaign and every variant, deployment, metric,
          test cycle, and report tied to it. This cannot be undone. The
          Meta ads themselves stay live on Meta&apos;s side — only the
          Kleiber-side records are removed, so you can re-import this
          same Meta campaign afterwards.
        </p>

        {!confirmArmed ? (
          <button
            type="button"
            onClick={() => setConfirmArmed(true)}
            className="mt-3 rounded border border-red-800/60 bg-red-900/30 px-3 py-1.5 text-xs text-red-200 hover:bg-red-900/50"
          >
            Delete campaign…
          </button>
        ) : (
          <div className="mt-3 space-y-2">
            <label className="block text-xs text-[var(--text-secondary)]">
              Type{" "}
              <span className="font-mono text-red-300">
                {campaign?.name}
              </span>{" "}
              to confirm:
              <input
                type="text"
                value={confirmText}
                onChange={(e) => setConfirmText(e.target.value)}
                className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--bg-subtle)] px-2 py-1 text-xs font-mono"
                autoFocus
              />
            </label>
            <div className="flex items-center gap-2">
              <Button
                onClick={handleDelete}
                disabled={!confirmMatches || deleteCampaign.isPending}
                loading={deleteCampaign.isPending}
                variant="destructive"
              >
                Permanently delete
              </Button>
              <button
                type="button"
                onClick={() => {
                  setConfirmArmed(false);
                  setConfirmText("");
                }}
                className="text-xs text-[var(--text-tertiary)] hover:text-[var(--text)]"
              >
                Cancel
              </button>
            </div>
            {deleteCampaign.error && (
              <p role="alert" className="text-xs text-red-300">
                Delete failed — {deleteCampaign.error.message}. Check
                the console logs and retry.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
