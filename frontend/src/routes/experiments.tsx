import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { ProposedPauseCard } from "@/components/ProposedPauseCard";
import { ProposedScaleCard } from "@/components/ProposedScaleCard";
import { ProposedVariantCard } from "@/components/ProposedVariantCard";
import { SuggestGenomeForm } from "@/components/SuggestGenomeForm";
import { Card, CardContent } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api/client";
import {
  useApproveProposal,
  useExperiments,
  useMe,
  useRejectProposal,
} from "@/lib/api/hooks";
import type {
  PendingApproval,
  PendingNewVariant,
  ProposedVariant,
} from "@/lib/api/types";

/**
 * Authed replacement for the tokenized /review/{token} page.
 *
 * Shows every pending proposed variant for the campaign, lets the
 * logged-in user approve or reject them, and exposes the same
 * "suggest your own copy" form as the email-based review page. The
 * tokenized page remains reachable for unauthenticated users — both
 * flows hit distinct backend endpoints.
 */
export function ExperimentsRoute() {
  const { campaignId = "" } = useParams();
  const me = useMe();
  const campaign = me.data?.campaigns.find((c) => c.id === campaignId);

  const experiments = useExperiments(campaignId);
  const approve = useApproveProposal(campaignId);
  const reject = useRejectProposal(campaignId);

  const [resolved, setResolved] = useState<Set<string>>(new Set());

  if (me.data && !campaign) {
    return <Navigate to="/dashboard" replace />;
  }

  const busy = approve.isPending || reject.isPending;

  const markResolved = (approvalId: string) => {
    setResolved((prev) => {
      const next = new Set(prev);
      next.add(approvalId);
      return next;
    });
  };

  const handleApprove = async (approvalId: string) => {
    try {
      await approve.mutateAsync(approvalId);
      markResolved(approvalId);
    } catch {
      /* error toast handled via mutation state below */
    }
  };

  const handleReject = async (approvalId: string) => {
    try {
      await reject.mutateAsync({ approvalId });
      markResolved(approvalId);
    } catch {
      /* error toast handled via mutation state below */
    }
  };

  const mutationError =
    approve.error instanceof ApiError
      ? approve.error
      : reject.error instanceof ApiError
        ? reject.error
        : null;

  return (
    <div>
      <div className="mb-6">
        <Link
          to={`/campaigns/${campaignId}`}
          className="text-xs text-[var(--accent)] no-underline hover:underline"
        >
          ← {campaign?.name ?? "Campaign"}
        </Link>
        <h1 className="mt-3 text-xl font-medium">Next week&rsquo;s experiments</h1>
        <p className="mt-1 text-xs text-[var(--text-tertiary)]">
          Review proposed variants, approve or reject them, and suggest new
          gene pool entries. Decisions sync back to the weekly generator.
        </p>
      </div>

      {experiments.isLoading ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="mt-3 h-3 w-full" />
                  <Skeleton className="mt-2 h-3 w-5/6" />
                  <Skeleton className="mt-2 h-3 w-2/3" />
                </div>
                <div className="flex gap-2">
                  <Skeleton className="h-8 w-20 rounded-[var(--radius-pill)]" />
                  <Skeleton className="h-8 w-20 rounded-[var(--radius-pill)]" />
                </div>
              </div>
            </Card>
          ))}
        </div>
      ) : null}

      {experiments.isError ? (
        <Card>
          <CardContent className="text-[var(--red)]">
            Could not load experiments. Please refresh the page.
          </CardContent>
        </Card>
      ) : null}

      {mutationError ? (
        <div className="mb-4 rounded-lg border border-[var(--red)] bg-[var(--bg-secondary)] p-3 text-xs text-[var(--red)]">
          {typeof mutationError.detail === "object" &&
          mutationError.detail !== null &&
          "detail" in (mutationError.detail as Record<string, unknown>)
            ? String((mutationError.detail as { detail: unknown }).detail)
            : mutationError.message}
        </div>
      ) : null}

      {experiments.data ? (
        <ExperimentsBody
          data={experiments.data}
          campaignId={campaignId}
          resolved={resolved}
          busy={busy}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      ) : null}
    </div>
  );
}

interface ExperimentsBodyProps {
  data: NonNullable<ReturnType<typeof useExperiments>["data"]>;
  campaignId: string;
  resolved: Set<string>;
  busy: boolean;
  onApprove: (approvalId: string) => void;
  onReject: (approvalId: string) => void;
}

function ExperimentsBody({
  data,
  campaignId,
  resolved,
  busy,
  onApprove,
  onReject,
}: ExperimentsBodyProps) {
  // Phase H: prefer the discriminated union from ``pending_approvals``
  // when the backend returned one; fall back to the legacy
  // ``proposed_variants`` list for old responses so the page keeps
  // working during rollout.
  const approvals: PendingApproval[] =
    data.pending_approvals && data.pending_approvals.length > 0
      ? data.pending_approvals
      : (data.proposed_variants ?? []).map(
          (pv: ProposedVariant): PendingNewVariant => ({
            kind: "new_variant",
            approval_id: pv.approval_id,
            variant_id: pv.variant_id ?? null,
            variant_code: pv.variant_code,
            genome: pv.genome,
            genome_summary: pv.genome_summary,
            hypothesis: pv.hypothesis,
            submitted_at: pv.submitted_at,
            classification: pv.classification,
            days_until_expiry: pv.days_until_expiry,
          }),
        );

  const visible = approvals.filter((a) => !resolved.has(a.approval_id));
  const resolvedCount = resolved.size;

  return (
    <>
      <section className="mb-8">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="text-[15px] font-medium">Pending proposals</h2>
          <span className="text-[11px] text-[var(--text-tertiary)]">
            {visible.length} pending
            {resolvedCount > 0 ? ` · ${resolvedCount} resolved` : ""}
          </span>
        </div>

        {approvals.length === 0 ? (
          <Card>
            <CardContent className="text-center text-[var(--text-secondary)]">
              <p>No pending proposals right now.</p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                The next cycle will surface pause and scale recommendations
                here for your review.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-3">
            {approvals.map((a) => {
              const isResolved = resolved.has(a.approval_id);
              if (a.kind === "pause_variant") {
                return (
                  <ProposedPauseCard
                    key={a.approval_id}
                    proposal={a}
                    onApprove={onApprove}
                    onReject={onReject}
                    busy={busy}
                    resolved={isResolved}
                  />
                );
              }
              if (a.kind === "scale_budget") {
                return (
                  <ProposedScaleCard
                    key={a.approval_id}
                    proposal={a}
                    onApprove={onApprove}
                    onReject={onReject}
                    busy={busy}
                    resolved={isResolved}
                  />
                );
              }
              if (a.kind === "new_variant") {
                // Re-use the existing card; it takes the legacy
                // ``ProposedVariant`` shape, which is structurally
                // identical to ``PendingNewVariant`` minus ``kind``.
                const legacy: ProposedVariant = {
                  approval_id: a.approval_id,
                  variant_id: a.variant_id ?? "",
                  variant_code: a.variant_code,
                  genome: a.genome,
                  genome_summary: a.genome_summary,
                  hypothesis: a.hypothesis,
                  submitted_at: a.submitted_at,
                  classification: a.classification,
                  days_until_expiry: a.days_until_expiry,
                };
                return (
                  <ProposedVariantCard
                    key={a.approval_id}
                    variant={legacy}
                    onApprove={onApprove}
                    onReject={onReject}
                    busy={busy}
                    resolved={isResolved}
                  />
                );
              }
              // promote_winner — placeholder branch (Phase H plan note)
              return (
                <Card key={a.approval_id}>
                  <CardContent className="text-[var(--text-secondary)]">
                    Promote-winner review coming soon.
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      <section className="mb-8">
        <SuggestGenomeForm
          campaignId={campaignId}
          allowedSlots={data.allowed_suggestion_slots}
        />
      </section>
    </>
  );
}
