import { Link, useParams } from "react-router-dom";

import { Card } from "@/components/ui/Card";
import { useMe } from "@/lib/api/hooks";

/**
 * Phase 3 stub: Phases 4-5 will replace this with a real overview page.
 * For now it simply confirms scoping works — the campaign id from the
 * URL is matched against the /api/me campaign list and we render a
 * "coming soon" card.
 */
export function CampaignDetailRoute() {
  const { campaignId = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  return (
    <div>
      <div className="mb-6">
        <Link to="/dashboard" className="text-xs text-[var(--accent)]">
          ← Back to campaigns
        </Link>
        <h1 className="mt-2 text-xl font-medium">
          {campaign?.name ?? "Campaign"}
        </h1>
        <p className="mt-1 text-xs text-[var(--text-tertiary)]">
          ID: <span className="font-mono">{campaignId}</span>
        </p>
      </div>
      <Card>
        <p className="text-sm text-[var(--text-secondary)]">
          Campaign overview, daily reports, weekly reports, and experiments
          are coming in the next phases. For now, the dashboard home lists
          every campaign you have access to.
        </p>
      </Card>
    </div>
  );
}
