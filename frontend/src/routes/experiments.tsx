import { useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";

import { ProposedVariantCard } from "@/components/ProposedVariantCard";
import { SuggestGenomeForm } from "@/components/SuggestGenomeForm";
import { Card, CardContent } from "@/components/ui/Card";
import { ApiError } from "@/lib/api/client";
import {
  useApproveProposal,
  useExperiments,
  useMe,
  useRejectProposal,
} from "@/lib/api/hooks";

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
        <Card>
          <CardContent className="text-[var(--text-tertiary)]">
            Loading experiments…
          </CardContent>
        </Card>
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
  const pending = data.proposed_variants.filter(
    (pv) => !resolved.has(pv.approval_id),
  );
  const resolvedCount = resolved.size;

  return (
    <>
      <section className="mb-8">
        <div className="mb-3 flex items-baseline gap-2">
          <h2 className="text-[15px] font-medium">Pending proposals</h2>
          <span className="text-[11px] text-[var(--text-tertiary)]">
            {pending.length} pending
            {resolvedCount > 0 ? ` · ${resolvedCount} resolved` : ""}
          </span>
        </div>

        {data.proposed_variants.length === 0 ? (
          <Card>
            <CardContent className="text-center text-[var(--text-secondary)]">
              <p>No pending proposals right now.</p>
              <p className="mt-1 text-xs text-[var(--text-tertiary)]">
                The next weekly report will bring fresh variants to review.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="flex flex-col gap-3">
            {data.proposed_variants.map((pv) => (
              <ProposedVariantCard
                key={pv.approval_id}
                variant={pv}
                onApprove={onApprove}
                onReject={onReject}
                busy={busy}
                resolved={resolved.has(pv.approval_id)}
              />
            ))}
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
