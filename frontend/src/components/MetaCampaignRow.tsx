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
 *
 * Ported to the warm-editorial palette — white rows with warm-paper
 * highlight for the selected state and a subtle tint for imported
 * rows. Dashboard primitives supply the status pill so the type
 * reads consistently across the app.
 */

import {
  StatusPill,
  type StatusKind,
} from "@/components/dashboard/primitives";
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

function statusKind(status: string): StatusKind {
  return status.toUpperCase() === "ACTIVE" ? "active" : "paused";
}

export function MetaCampaignRow({
  campaign,
  selected,
  disabled,
  onToggle,
}: Props) {
  const isLocked = disabled || campaign.already_imported;

  const background = isLocked
    ? "var(--paper-2)"
    : selected
      ? "oklch(97% 0.04 60 / 0.6)"
      : "white";

  const borderColor = selected && !isLocked
    ? "var(--accent)"
    : "var(--border)";

  return (
    <label
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 12,
        padding: "14px 16px",
        borderRadius: 12,
        border: `1px solid ${borderColor}`,
        background,
        transition: "all 0.15s",
        cursor: isLocked ? "not-allowed" : "pointer",
        opacity: isLocked ? 0.65 : 1,
      }}
    >
      <input
        type="checkbox"
        checked={selected}
        disabled={isLocked}
        onChange={() => onToggle(campaign.meta_campaign_id)}
        style={{
          width: 16,
          height: 16,
          marginTop: 2,
          accentColor: "var(--ink)",
          cursor: isLocked ? "not-allowed" : "pointer",
        }}
      />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            alignItems: "center",
          }}
        >
          <h3
            style={{
              margin: 0,
              fontSize: 13.5,
              fontWeight: 500,
              color: "var(--ink)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {campaign.name}
            {campaign.already_imported && (
              <span
                style={{
                  marginLeft: 8,
                  fontFamily: "var(--font-mono)",
                  fontSize: 9.5,
                  color: "oklch(40% 0.14 145)",
                  letterSpacing: "0.06em",
                }}
              >
                IMPORTED
              </span>
            )}
          </h3>
          <StatusPill kind={statusKind(campaign.status)}>
            {campaign.status}
          </StatusPill>
        </div>
        <dl
          style={{
            margin: "6px 0 0",
            display: "flex",
            flexWrap: "wrap",
            gap: "4px 16px",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--muted)",
          }}
        >
          <Entry label="budget" value={formatBudget(campaign.daily_budget)} />
          {campaign.objective && (
            <Entry label="objective" value={campaign.objective} />
          )}
          <Entry label="id" value={campaign.meta_campaign_id} />
        </dl>
      </div>
    </label>
  );
}

function Entry({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "inline-flex", gap: 5 }}>
      <dt style={{ color: "var(--muted-2)" }}>{label}</dt>
      <dd style={{ margin: 0, color: "var(--ink-2)" }}>{value}</dd>
    </div>
  );
}
