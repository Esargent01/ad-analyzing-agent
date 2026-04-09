import { GenomePills } from "@/components/GenomePills";
import { Button } from "@/components/ui/Button";
import type { ProposedVariant } from "@/lib/api/types";
import { cn } from "@/lib/cn";

interface ProposedVariantCardProps {
  variant: ProposedVariant;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
  /** Disable action buttons while any mutation is in flight. */
  busy?: boolean;
  /** When true the card fades — used after a successful approve/reject. */
  resolved?: boolean;
}

/**
 * One pending proposal in the authed experiments page. Mirrors the
 * `.proposal` card from `src/dashboard/templates/review.html`: header
 * with variant code + genome summary + new/expiring badge, genome
 * pills, optional hypothesis, and two action buttons.
 */
export function ProposedVariantCard({
  variant,
  onApprove,
  onReject,
  busy = false,
  resolved = false,
}: ProposedVariantCardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-[var(--border)] p-4 transition-opacity",
        resolved && "pointer-events-none opacity-40",
      )}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0 text-[13px]">
          <span className="font-mono font-semibold text-[var(--accent)]">
            {variant.variant_code}
          </span>
          <span className="text-[var(--text-tertiary)]"> · </span>
          <span className="text-[var(--text)]">{variant.genome_summary}</span>
        </div>
        {variant.classification === "expiring_soon" ? (
          <span className="inline-block whitespace-nowrap rounded-[12px] bg-[#FFF4D6] px-2.5 py-0.5 text-[11px] font-medium text-[#B07C1A]">
            Expires in {variant.days_until_expiry} day
            {variant.days_until_expiry === 1 ? "" : "s"}
          </span>
        ) : (
          <span className="inline-block whitespace-nowrap rounded-[12px] bg-[#EDF4EC] px-2.5 py-0.5 text-[11px] font-medium text-[#2B6B30]">
            New
          </span>
        )}
      </div>

      <GenomePills genome={variant.genome} />

      {variant.hypothesis ? (
        <div className="mt-2 text-xs italic leading-relaxed text-[var(--text-secondary)]">
          &ldquo;{variant.hypothesis}&rdquo;
        </div>
      ) : null}

      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          size="sm"
          className="bg-[var(--green)] hover:brightness-110"
          onClick={() => onApprove(variant.approval_id)}
          disabled={busy || resolved}
        >
          Approve
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          className="border-[var(--red)] text-[var(--red)] hover:bg-[var(--red)] hover:text-white"
          onClick={() => onReject(variant.approval_id)}
          disabled={busy || resolved}
        >
          Reject
        </Button>
      </div>
    </div>
  );
}
