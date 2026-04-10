import { GenomePills } from "@/components/GenomePills";
import { Button } from "@/components/ui/Button";
import type { PendingPauseVariant } from "@/lib/api/types";
import { cn } from "@/lib/cn";

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
 * ``approval_queue`` with the statistical evidence it used and the
 * user's click on "Confirm pause" is what actually fires
 * ``MetaAdapter.pause_ad``. Two flavours of reason land here:
 *
 * - ``statistically_significant_loser`` — the variant lost a
 *   two-proportion z-test against the baseline
 * - ``audience_fatigue`` — CTR has declined for 3+ consecutive days
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
      : "Statistically significant loser";

  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--red)] bg-[var(--bg-secondary)] p-4 transition-opacity",
        resolved && "pointer-events-none opacity-40",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 text-[13px]">
          <span className="font-mono font-semibold text-[var(--red)]">
            Pause {variant_code ?? platform_ad_id}
          </span>
          <span className="text-[var(--text-tertiary)]"> · </span>
          <span className="text-[var(--text)]">
            The agent recommends taking this ad offline.
          </span>
        </div>
        <span className="inline-block whitespace-nowrap rounded-[12px] bg-[#FBE3E3] px-2.5 py-0.5 text-[11px] font-medium text-[#9B2226]">
          {reasonLabel}
        </span>
      </div>

      {Object.keys(genome_snapshot).length > 0 ? (
        <GenomePills genome={genome_snapshot} />
      ) : null}

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-[var(--text-secondary)] sm:grid-cols-4">
        {reason === "statistically_significant_loser" ? (
          <>
            <div>
              <dt className="text-[var(--text-tertiary)]">Variant CTR</dt>
              <dd className="font-mono">{formatPct(evidence.variant_ctr)}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Baseline CTR</dt>
              <dd className="font-mono">{formatPct(evidence.baseline_ctr)}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">p-value</dt>
              <dd className="font-mono">{formatP(evidence.p_value)}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Impressions</dt>
              <dd className="font-mono">{formatInt(evidence.impressions)}</dd>
            </div>
          </>
        ) : (
          <>
            <div>
              <dt className="text-[var(--text-tertiary)]">Days declining</dt>
              <dd className="font-mono">
                {formatInt(evidence.consecutive_decline_days)}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Trend slope</dt>
              <dd className="font-mono">{formatP(evidence.trend_slope)}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Current CTR</dt>
              <dd className="font-mono">{formatPct(evidence.variant_ctr)}</dd>
            </div>
            <div>
              <dt className="text-[var(--text-tertiary)]">Impressions</dt>
              <dd className="font-mono">{formatInt(evidence.impressions)}</dd>
            </div>
          </>
        )}
      </dl>

      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          size="sm"
          className="bg-[var(--red)] hover:brightness-110"
          onClick={() => onApprove(proposal.approval_id)}
          disabled={busy || resolved}
        >
          Confirm pause
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => onReject(proposal.approval_id)}
          disabled={busy || resolved}
        >
          Keep running
        </Button>
      </div>
    </div>
  );
}
