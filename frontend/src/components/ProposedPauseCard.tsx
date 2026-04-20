import {
  GenomeSlots,
  StatusPill,
} from "@/components/dashboard/primitives";
import type { PendingPauseVariant } from "@/lib/api/types";

interface ProposedPauseCardProps {
  proposal: PendingPauseVariant;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
  busy?: boolean;
  resolved?: boolean;
}

/**
 * Phase H card: agent proposes pausing a currently-running ad.
 *
 * The agent never pauses ads autonomously — it queues this row into
 * ``approval_queue`` with the statistical evidence it used, and the
 * user's click on "Confirm pause" is what actually fires
 * ``MetaAdapter.pause_ad``. Two flavours of reason land here:
 *
 * - ``statistically_significant_loser`` — the variant lost a
 *   two-proportion z-test against the baseline
 * - ``audience_fatigue`` — CTR has declined for 3+ consecutive days
 *
 * Visuals: danger-tinted white card, red status chip, 4-up mono
 * stats row with the exact numbers that triggered the proposal.
 */
export function ProposedPauseCard({
  proposal,
  onApprove,
  onReject,
  busy = false,
  resolved = false,
}: ProposedPauseCardProps) {
  const { evidence, reason, variant_code, platform_ad_id, genome_snapshot } =
    proposal;

  const formatPct = (v: number | null | undefined) =>
    v == null ? "—" : `${(Number(v) * 100).toFixed(2)}%`;
  const formatP = (v: number | null | undefined) =>
    v == null ? "—" : Number(v).toFixed(4);
  const formatInt = (v: number | null | undefined) =>
    v == null ? "—" : Number(v).toLocaleString();

  const reasonLabel =
    reason === "audience_fatigue"
      ? "Audience fatigue"
      : "Significant loser";

  return (
    <div
      style={{
        padding: 20,
        border: "1px solid oklch(88% 0.08 28)",
        borderRadius: 12,
        background: "oklch(98% 0.02 28)",
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
                color: "oklch(40% 0.16 28)",
              }}
            >
              Pause {variant_code ?? platform_ad_id}
            </span>
            <StatusPill kind="danger">{reasonLabel}</StatusPill>
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
            The agent recommends taking this ad offline. Review the
            numbers, then confirm or keep it running.
          </p>
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onReject(proposal.approval_id)}
            disabled={busy || resolved}
          >
            Keep running
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            onClick={() => onApprove(proposal.approval_id)}
            disabled={busy || resolved}
          >
            Confirm pause
          </button>
        </div>
      </div>

      {Object.keys(genome_snapshot).length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <GenomeSlots genome={genome_snapshot} />
        </div>
      )}

      <dl
        data-ds-grid
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
          margin: 0,
        }}
      >
        {reason === "statistically_significant_loser" ? (
          <>
            <EvidenceCell label="Variant CTR" value={formatPct(evidence.variant_ctr)} />
            <EvidenceCell label="Baseline CTR" value={formatPct(evidence.baseline_ctr)} />
            <EvidenceCell label="p-value" value={formatP(evidence.p_value)} />
            <EvidenceCell label="Impressions" value={formatInt(evidence.impressions)} />
          </>
        ) : (
          <>
            <EvidenceCell
              label="Days declining"
              value={formatInt(evidence.consecutive_decline_days)}
            />
            <EvidenceCell label="Trend slope" value={formatP(evidence.trend_slope)} />
            <EvidenceCell label="Current CTR" value={formatPct(evidence.variant_ctr)} />
            <EvidenceCell label="Impressions" value={formatInt(evidence.impressions)} />
          </>
        )}
      </dl>
    </div>
  );
}

function EvidenceCell({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: 10,
        background: "white",
        borderRadius: 8,
        border: "1px solid var(--border-soft)",
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
