import { GenomePills } from "@/components/GenomePills";
import { Button } from "@/components/ui/Button";
import type { PendingScaleBudget } from "@/lib/api/types";
import { cn } from "@/lib/cn";

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
 * Source of the proposal is Thompson sampling — the agent's
 * posterior over each variant's CTR assigns shares of the daily
 * budget, and any variant whose proposed share exceeds its current
 * budget by ≥5% gets a row in ``approval_queue``. The user
 * confirms and the executor pushes the new budget to Meta.
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

  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--green)] bg-[var(--bg-secondary)] p-4 transition-opacity",
        resolved && "pointer-events-none opacity-40",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 text-[13px]">
          <span className="font-mono font-semibold text-[var(--green)]">
            {increasing ? "Scale up" : "Scale down"}{" "}
            {variant_code ?? platform_ad_id}
          </span>
          <span className="text-[var(--text-tertiary)]"> · </span>
          <span className="text-[var(--text)]">
            Thompson sampling says this ad deserves
            {increasing ? " more" : " less"} budget.
          </span>
        </div>
        <span className="inline-block whitespace-nowrap rounded-[12px] bg-[#EDF4EC] px-2.5 py-0.5 text-[11px] font-medium text-[#2B6B30]">
          {increasing ? "+" : ""}
          {deltaPct.toFixed(0)}%
        </span>
      </div>

      {Object.keys(genome_snapshot).length > 0 ? (
        <GenomePills genome={genome_snapshot} />
      ) : null}

      <div className="mt-3 flex items-center gap-2 text-[13px] font-mono">
        <span className="text-[var(--text-secondary)]">{fmtUSD(current)}</span>
        <span className="text-[var(--text-tertiary)]">→</span>
        <span
          className={cn(
            "font-semibold",
            increasing ? "text-[var(--green)]" : "text-[var(--red)]",
          )}
        >
          {fmtUSD(proposed)}
        </span>
        <span className="text-[11px] text-[var(--text-tertiary)]">/ day</span>
      </div>

      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-[var(--text-secondary)] sm:grid-cols-3">
        <div>
          <dt className="text-[var(--text-tertiary)]">Posterior mean CTR</dt>
          <dd className="font-mono">{fmtPct(evidence.posterior_mean)}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-tertiary)]">Share of allocation</dt>
          <dd className="font-mono">{fmtPct(evidence.share_of_allocation)}</dd>
        </div>
        <div>
          <dt className="text-[var(--text-tertiary)]">Method</dt>
          <dd className="font-mono">
            {evidence.allocation_method ?? "thompson_sampling"}
          </dd>
        </div>
      </dl>

      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          size="sm"
          className="bg-[var(--green)] hover:brightness-110"
          onClick={() => onApprove(proposal.approval_id)}
          disabled={busy || resolved}
        >
          Confirm budget change
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => onReject(proposal.approval_id)}
          disabled={busy || resolved}
        >
          Keep budget
        </Button>
      </div>
    </div>
  );
}
