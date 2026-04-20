import {
  GenomeSlots,
  StatusPill,
} from "@/components/dashboard/primitives";
import type { PendingScaleBudget } from "@/lib/api/types";

interface ProposedScaleCardProps {
  proposal: PendingScaleBudget;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
  busy?: boolean;
  resolved?: boolean;
}

/**
 * Phase H card: agent proposes a budget change for a running ad.
 *
 * Source of the proposal is Thompson sampling — the agent's posterior
 * over each variant's CTR assigns shares of the daily budget, and any
 * variant whose proposed share exceeds its current budget by ≥5%
 * gets a row in ``approval_queue``. The user confirms and the
 * executor pushes the new budget to Meta.
 *
 * Visuals: warm-paper white card, winning-green status chip (or
 * fatigue-amber when scaling down), prominent current → proposed
 * number line, 3-up mono evidence row.
 */
export function ProposedScaleCard({
  proposal,
  onApprove,
  onReject,
  busy = false,
  resolved = false,
}: ProposedScaleCardProps) {
  const {
    current_budget,
    proposed_budget,
    evidence,
    variant_code,
    platform_ad_id,
    genome_snapshot,
  } = proposal;

  const current = Number(current_budget);
  const proposed = Number(proposed_budget);
  const delta = proposed - current;
  const deltaPct = current > 0 ? (delta / current) * 100 : 0;
  const increasing = delta >= 0;

  const fmtUSD = (v: number) =>
    Number.isFinite(v)
      ? `$${v.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
      : "—";
  const fmtPct = (v: number | null | undefined) =>
    v == null ? "—" : `${(Number(v) * 100).toFixed(2)}%`;

  const arrowColor = increasing
    ? "oklch(40% 0.14 145)"
    : "oklch(48% 0.16 28)";

  return (
    <div
      style={{
        padding: 20,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
        transition: "opacity 0.2s",
        opacity: resolved ? 0.4 : 1,
        pointerEvents: resolved ? "none" : undefined,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: 16,
          marginBottom: 10,
          flexWrap: "wrap",
        }}
      >
        <div style={{ minWidth: 0, flex: 1 }}>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 14,
                fontWeight: 500,
                color: "var(--ink)",
              }}
            >
              {increasing ? "Scale up" : "Scale down"}{" "}
              {variant_code ?? platform_ad_id}
            </span>
            <StatusPill kind={increasing ? "winner" : "fatigue"}>
              {increasing ? "+" : ""}
              {deltaPct.toFixed(0)}%
            </StatusPill>
          </div>
          <p
            style={{
              fontSize: 13.5,
              color: "var(--ink-2)",
              margin: "8px 0 0",
              maxWidth: 620,
              lineHeight: 1.5,
            }}
          >
            Thompson sampling says this ad deserves
            {increasing ? " more" : " less"} budget. Review the evidence,
            then confirm the change.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onReject(proposal.approval_id)}
            disabled={busy || resolved}
          >
            Keep budget
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => onApprove(proposal.approval_id)}
            disabled={busy || resolved}
          >
            Confirm budget change
          </button>
        </div>
      </div>

      {Object.keys(genome_snapshot).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <GenomeSlots genome={genome_snapshot} />
        </div>
      )}

      {/* Big number transition */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: 14,
          background: "var(--paper-2)",
          borderRadius: 10,
          marginBottom: 14,
          fontFamily: "var(--font-mono)",
        }}
      >
        <span style={{ fontSize: 16, color: "var(--muted)" }}>
          {fmtUSD(current)}
        </span>
        <span style={{ color: "var(--muted)" }}>→</span>
        <span
          style={{
            fontSize: 18,
            fontWeight: 500,
            color: arrowColor,
          }}
        >
          {fmtUSD(proposed)}
        </span>
        <span style={{ fontSize: 11, color: "var(--muted)" }}>/ day</span>
      </div>

      <dl
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 12,
          margin: 0,
        }}
      >
        <EvidenceCell
          label="Posterior mean CTR"
          value={fmtPct(evidence.posterior_mean)}
        />
        <EvidenceCell
          label="Share of allocation"
          value={fmtPct(evidence.share_of_allocation)}
        />
        <EvidenceCell
          label="Method"
          value={evidence.allocation_method ?? "thompson_sampling"}
        />
      </dl>
    </div>
  );
}

function EvidenceCell({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: 10,
        background: "var(--paper-2)",
        borderRadius: 8,
      }}
    >
      <dt className="eyebrow" style={{ fontSize: 9.5 }}>
        {label}
      </dt>
      <dd
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          fontWeight: 500,
          margin: "2px 0 0",
          color: "var(--ink)",
        }}
      >
        {value}
      </dd>
    </div>
  );
}
