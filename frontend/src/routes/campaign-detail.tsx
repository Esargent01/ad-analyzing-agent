import { Navigate, useNavigate, useParams } from "react-router-dom";

import { DashPage } from "@/components/dashboard/DashPage";
import {
  DangerZone,
  QuickLink,
  StatTile,
  StatusPill,
} from "@/components/dashboard/primitives";
import {
  useDailyDates,
  useDeleteCampaign,
  useExperiments,
  useMe,
  useWeeklyIndex,
} from "@/lib/api/hooks";
import { formatDateLabel } from "@/lib/format";

/**
 * Campaign overview — the landing page after you click a campaign
 * card on the dashboard home.
 *
 * Port of ``kleiber-agent-deign/project/src/dashboard/screens-a.jsx::CampaignOverview``.
 * Layout:
 *
 * 1. DashPage frame with breadcrumb (Dashboard → {campaign name}),
 *    lowercase editorial title, subtitle with status pill + ID, and
 *    actions (primary "Approvals" button with pending-count badge).
 * 2. Three StatTile-s: daily reports count / weekly reports count /
 *    pending approvals count (red tint when > 0).
 * 3. "GO TO" eyebrow + three QuickLink cards (daily, weekly,
 *    experiments).
 * 4. DangerZone at the bottom — type-to-confirm delete flow, wired
 *    to the existing ``useDeleteCampaign`` mutation + cascade.
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

  const dailyCount = daily.data?.dates.length ?? 0;
  const weeklyCount = weekly.data?.weeks.length ?? 0;
  const pendingCount =
    experiments.data?.pending_approvals?.length ??
    experiments.data?.proposed_variants.length ??
    0;
  const latestDaily = daily.data?.dates[0];
  const latestWeek = weekly.data?.weeks[0];

  const handleDelete = async () => {
    try {
      await deleteCampaign.mutateAsync(campaignId);
      navigate("/dashboard", { replace: true });
    } catch {
      // Mutation error state surfaces in the DangerZone component.
    }
  };

  // 404-equivalent: authed user, but campaign isn't in their list.
  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <DashPage
      crumb={[
        { label: "Dashboard", href: "/dashboard" },
        { label: campaign?.name ?? "Campaign" },
      ]}
      title={campaign?.name ?? "campaign"}
      sub={
        campaign ? (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 10,
              flexWrap: "wrap",
            }}
          >
            <StatusPill kind={campaign.is_active ? "active" : "paused"}>
              {campaign.is_active ? "active" : "paused"}
            </StatusPill>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--muted)",
              }}
            >
              {campaign.id}
            </span>
          </span>
        ) : null
      }
      actions={
        <button
          type="button"
          className="btn btn-primary btn-sm"
          onClick={() => navigate(`/campaigns/${campaignId}/experiments`)}
          style={{
            textDecoration: "none",
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          Approvals
          {pendingCount > 0 && (
            <span
              style={{
                background: "var(--accent)",
                color: "white",
                fontSize: 10,
                padding: "1px 6px",
                borderRadius: 99,
                fontWeight: 500,
              }}
            >
              {pendingCount}
            </span>
          )}
        </button>
      }
    >
      <div
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 16,
          marginBottom: 28,
        }}
      >
        <StatTile
          label="DAILY REPORTS"
          value={dailyCount}
          sub={
            latestDaily
              ? `latest ${formatDateLabel(latestDaily)}`
              : "no reports yet"
          }
        />
        <StatTile
          label="WEEKLY REPORTS"
          value={weeklyCount}
          sub={latestWeek ? `latest ${latestWeek.label}` : "no reports yet"}
        />
        <StatTile
          label="PENDING APPROVALS"
          value={pendingCount}
          sub={pendingCount > 0 ? "waiting on you" : "nothing to review"}
          bad={pendingCount > 0}
        />
      </div>

      <div className="eyebrow" style={{ marginBottom: 14 }}>
        GO TO
      </div>
      <div
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 14,
        }}
      >
        <QuickLink
          label="Daily reports"
          desc="Day-by-day funnel metrics and variant performance."
          onClick={() => navigate(`/campaigns/${campaignId}/reports/daily`)}
        />
        <QuickLink
          label="Weekly reports"
          desc="Leaderboard, element rankings, and pairwise lift."
          onClick={() => navigate(`/campaigns/${campaignId}/reports/weekly`)}
        />
        <QuickLink
          label="Next week's experiments"
          desc="Proposed variants and actions awaiting approval."
          badge={pendingCount}
          onClick={() => navigate(`/campaigns/${campaignId}/experiments`)}
        />
      </div>

      {campaign && (
        <DangerZone
          campaignName={campaign.name}
          onDelete={handleDelete}
          isPending={deleteCampaign.isPending}
          errorMessage={
            deleteCampaign.error ? deleteCampaign.error.message : null
          }
        />
      )}
    </DashPage>
  );
}
