import { Card } from "@/components/ui/Card";
import { useMyUsage } from "@/lib/api/hooks";
import { formatIntComma } from "@/lib/format";

/**
 * Format a USD amount with enough precision for sub-cent LLM costs.
 *
 * - >= $1  : `$12.34`
 * - >= $0.01 : `$0.03`
 * - > 0  :  `$0.0012`  (four decimals so sub-cent spend is visible)
 * - 0    :  `$0.00`
 */
function formatUsdPrecise(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "$0.00";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return "$0.00";
  if (n === 0) return "$0.00";
  if (Math.abs(n) >= 1) {
    return `$${n.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })}`;
  }
  if (Math.abs(n) >= 0.01) {
    return `$${n.toFixed(2)}`;
  }
  return `$${n.toFixed(4)}`;
}

/**
 * "This period" cost tile for the dashboard home.
 *
 * Renders the user's trailing 30-day spend from the ``/api/me/usage``
 * endpoint. Click-through links to a richer breakdown view (deferred
 * — for now the click just deep-links to the dashboard, a placeholder
 * that keeps the layout consistent with the other hover targets).
 */
export function UsageTile() {
  const usage = useMyUsage();

  if (usage.isLoading) {
    return (
      <Card>
        <p className="label">Usage (last 30 days)</p>
        <p className="mt-2 text-xs text-[var(--text-tertiary)]">Loading…</p>
      </Card>
    );
  }

  if (usage.isError || !usage.data) {
    return (
      <Card>
        <p className="label">Usage (last 30 days)</p>
        <p className="mt-2 text-xs text-[var(--text-tertiary)]">
          Couldn't load usage data.
        </p>
      </Card>
    );
  }

  const data = usage.data;
  const topCampaign = data.by_campaign[0];
  const topService = data.by_service[0];

  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <p className="label">Usage (last 30 days)</p>
        <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
          {data.from_date} → {data.to_date}
        </span>
      </div>

      <div className="mt-3 flex items-baseline gap-3">
        <span className="text-2xl font-medium text-[var(--text)]">
          {formatUsdPrecise(data.total_cost_usd)}
        </span>
        <span className="text-xs text-[var(--text-tertiary)]">
          {formatIntComma(data.total_calls)} call
          {data.total_calls === 1 ? "" : "s"}
        </span>
      </div>

      {data.by_service.length > 0 && (
        <div className="mt-3 space-y-1 text-xs">
          {data.by_service.map((row) => (
            <div
              key={row.service}
              className="flex items-center justify-between"
            >
              <span className="text-[var(--text-secondary)]">
                {row.service === "llm"
                  ? "LLM"
                  : row.service === "meta_api"
                  ? "Meta API"
                  : row.service}
              </span>
              <span className="tabular-nums text-[var(--text-tertiary)]">
                {formatUsdPrecise(row.cost_usd)} ·{" "}
                {formatIntComma(row.calls)}
              </span>
            </div>
          ))}
        </div>
      )}

      {topCampaign && topCampaign.campaign_name && (
        <p className="mt-3 text-xs text-[var(--text-tertiary)]">
          Top spender:{" "}
          <span className="text-[var(--text-secondary)]">
            {topCampaign.campaign_name}
          </span>{" "}
          ({formatUsdPrecise(topCampaign.cost_usd)})
        </p>
      )}

      {!topCampaign && !topService && (
        <p className="mt-3 text-xs text-[var(--text-tertiary)]">
          No activity yet — run a cycle to start tracking usage.
        </p>
      )}
    </Card>
  );
}
