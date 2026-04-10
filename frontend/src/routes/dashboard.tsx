import { Link } from "react-router-dom";

import { ConnectMetaCard } from "@/components/ConnectMetaCard";
import { StatusPill } from "@/components/StatusPill";
import { UsageTile } from "@/components/UsageTile";
import { Card } from "@/components/ui/Card";
import { useMe, useMetaStatus } from "@/lib/api/hooks";

export function DashboardRoute() {
  const me = useMe();
  const metaStatus = useMetaStatus();
  const campaigns = me.data?.campaigns ?? [];
  const metaConnected = metaStatus.data?.connected ?? false;

  return (
    <div>
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="label">Dashboard</p>
          <h1 className="mt-1 text-xl font-medium">Campaigns</h1>
          <p className="mt-1 text-xs text-[var(--text-secondary)]">
            {campaigns.length === 0
              ? "You don't have access to any campaigns yet."
              : `${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"}`}
          </p>
        </div>
        {metaConnected && (
          <Link
            to="/campaigns/import"
            className="inline-flex h-8 items-center justify-center rounded bg-[var(--accent)] px-3 text-xs font-medium text-white no-underline transition-colors hover:brightness-110 hover:no-underline"
          >
            Import campaigns
          </Link>
        )}
      </div>

      <ConnectMetaCard />

      <div className="mb-6">
        <UsageTile />
      </div>

      {campaigns.length === 0 ? (
        <Card>
          {metaConnected ? (
            <>
              <p className="text-sm text-[var(--text-secondary)]">
                You don't have any campaigns yet. Import campaigns from your
                connected Meta ad account to get started.
              </p>
              <Link
                to="/campaigns/import"
                className="mt-3 inline-flex h-8 items-center justify-center rounded bg-[var(--accent)] px-3 text-xs font-medium text-white no-underline transition-colors hover:brightness-110 hover:no-underline"
              >
                Import campaigns
              </Link>
            </>
          ) : (
            <p className="text-sm text-[var(--text-secondary)]">
              Connect your Meta account above, then click{" "}
              <strong>Import campaigns</strong> to get started.
            </p>
          )}
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {campaigns.map((campaign) => (
            <Link
              key={campaign.id}
              to={`/campaigns/${campaign.id}`}
              className="block rounded-lg border border-[var(--border)] bg-[var(--bg)] p-5 transition-colors hover:border-[var(--accent)] no-underline hover:no-underline"
            >
              <div className="mb-2 flex items-center justify-between">
                <StatusPill kind={campaign.is_active ? "active" : "paused"}>
                  {campaign.is_active ? "Active" : "Paused"}
                </StatusPill>
              </div>
              <h2 className="text-[15px] font-medium text-[var(--text)]">
                {campaign.name}
              </h2>
              <p className="mt-2 text-xs text-[var(--text-tertiary)]">
                View reports & experiments →
              </p>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
