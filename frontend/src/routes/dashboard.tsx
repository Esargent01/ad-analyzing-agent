import { Link } from "react-router-dom";

import { StatusPill } from "@/components/StatusPill";
import { Card } from "@/components/ui/Card";
import { useMe } from "@/lib/api/hooks";

export function DashboardRoute() {
  const me = useMe();
  const campaigns = me.data?.campaigns ?? [];

  return (
    <div>
      <div className="mb-6">
        <p className="label">Dashboard</p>
        <h1 className="mt-1 text-xl font-medium">Campaigns</h1>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          {campaigns.length === 0
            ? "You don't have access to any campaigns yet."
            : `${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"}`}
        </p>
      </div>

      {campaigns.length === 0 ? (
        <Card>
          <p className="text-sm text-[var(--text-secondary)]">
            Ask your admin to grant you access with:
          </p>
          <pre className="mt-3 overflow-x-auto rounded bg-[var(--bg-secondary)] p-3 text-xs">
            python -m src.main grant-access --email {me.data?.email ?? "you@company.com"} --campaign-id &lt;uuid&gt;
          </pre>
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
