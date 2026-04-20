import {
  GenomeSlots,
  StatusPill,
} from "@/components/dashboard/primitives";
import type { ProposedVariant } from "@/lib/api/types";

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
 * Pending variant proposal card on the experiments page.
 *
 * Ported to the warm-editorial system — white card with a clear
 * header row (variant code + PROPOSED status pill + hypothesis snippet),
 * element-chip genome row, and pill-shaped Approve / Reject buttons
 * sitting to the right. Matches the layout in the design drop at
 * ``kleiber-agent-deign/project/src/dashboard/screens-b.jsx::Experiments``.
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
              {variant.variant_code}
            </span>
            <StatusPill kind="new">PROPOSED</StatusPill>
            {variant.classification === "expiring_soon" && (
              <StatusPill kind="fatigue">
                Expires in {variant.days_until_expiry}d
              </StatusPill>
            )}
          </div>
          <div
            style={{
              fontSize: 13.5,
              color: "var(--muted)",
              margin: "8px 0 0",
              maxWidth: 620,
              lineHeight: 1.5,
            }}
          >
            {variant.genome_summary}
          </div>
          {variant.hypothesis && (
            <div
              style={{
                fontSize: 12.5,
                color: "var(--muted-2)",
                margin: "6px 0 0",
                fontStyle: "italic",
                maxWidth: 620,
                lineHeight: 1.5,
              }}
            >
              &ldquo;{variant.hypothesis}&rdquo;
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => onReject(variant.approval_id)}
            disabled={busy || resolved}
          >
            Reject
          </button>
          <button
            type="button"
            className="btn btn-primary btn-sm"
            onClick={() => onApprove(variant.approval_id)}
            disabled={busy || resolved}
          >
            Approve
          </button>
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <GenomeSlots genome={variant.genome} />
      </div>
    </div>
  );
}
