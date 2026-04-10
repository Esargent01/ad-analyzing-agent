/**
 * Single row in the Meta campaign picker.
 *
 * Renders one campaign from the user's ad account with:
 * - A checkbox bound to the parent's selection state
 * - The campaign name, Meta status (ACTIVE / PAUSED / ...)
 * - Daily budget, objective (if present)
 * - An "Already imported" badge that disables the checkbox when set
 *
 * The row is intentionally dumb — it doesn't own any state. The
 * import page passes `selected` + `onToggle` in.
 */

import { StatusPill } from "@/components/StatusPill";
import type { ImportableCampaign } from "@/lib/api/types";

interface Props {
  campaign: ImportableCampaign;
  selected: boolean;
  disabled?: boolean;
  onToggle: (metaCampaignId: string) => void;
}

function formatBudget(budget: number | null): string {
  if (budget == null || Number.isNaN(budget)) return "—";
  return `$${budget.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function statusKind(
  status: string,
): "active" | "paused" | "new" | "fatigue" | "winner" {
  if (status.toUpperCase() === "ACTIVE") return "active";
  return "paused";
}

export function MetaCampaignRow({
  campaign,
  selected,
  disabled,
  onToggle,
}: Props) {
  const isLocked = disabled || campaign.already_imported;
  const rowClasses = [
    "flex items-start gap-3 rounded-lg border px-4 py-3 transition-colors",
    isLocked
      ? "border-[var(--border)] bg-[var(--bg-secondary)] opacity-60"
      : selected
      ? "border-[var(--accent)] bg-[var(--bg)]"
      : "border-[var(--border)] bg-[var(--bg)] hover:border-[var(--accent)]",
  ].join(" ");

  return (
    <label className={rowClasses}>
      <input
        type="checkbox"
        className="mt-1 h-4 w-4 cursor-pointer accent-[var(--accent)] disabled:cursor-not-allowed"
        checked={selected}
        disabled={isLocked}
        onChange={() => onToggle(campaign.meta_campaign_id)}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-3">
          <h3 className="truncate text-sm font-medium text-[var(--text)]">
            {campaign.name}
          </h3>
          <StatusPill kind={statusKind(campaign.status)}>
            {campaign.status}
          </StatusPill>
        </div>
        <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--text-tertiary)]">
          <div className="flex gap-1">
            <dt>Budget:</dt>
            <dd className="text-[var(--text-secondary)]">
              {formatBudget(campaign.daily_budget)}
            </dd>
          </div>
          {campaign.objective && (
            <div className="flex gap-1">
              <dt>Objective:</dt>
              <dd className="text-[var(--text-secondary)]">
                {campaign.objective}
              </dd>
            </div>
          )}
          <div className="flex gap-1">
            <dt>Meta ID:</dt>
            <dd className="font-mono text-[var(--text-secondary)]">
              {campaign.meta_campaign_id}
            </dd>
          </div>
        </dl>
        {campaign.already_imported && (
          <p className="mt-1 text-[11px] uppercase tracking-wide text-[var(--text-tertiary)]">
            Already imported
          </p>
        )}
      </div>
    </label>
  );
}
