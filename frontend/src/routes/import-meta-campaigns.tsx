/**
 * Phase D self-serve import page.
 *
 * Flow:
 * 1. Fetch the connected user's Meta campaigns (`useImportableCampaigns`)
 * 2. Render one `<MetaCampaignRow />` per result with checkboxes
 * 3. Submit the selected IDs via `useImportCampaigns`
 * 4. On success, show the per-campaign result (imported / failed)
 *    and redirect back to the dashboard after a short beat
 *
 * Guardrails:
 * - If Meta is not connected, redirect to /dashboard (the card there
 *   handles the connect flow)
 * - The submit button is disabled when the selection would push the
 *   user over `quota_max`
 * - Already-imported rows are locked via `MetaCampaignRow`'s disabled
 *   prop
 */

import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { MetaCampaignRow } from "@/components/MetaCampaignRow";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/Card";
import { ApiError } from "@/lib/api/client";
import {
  useImportCampaigns,
  useImportableCampaigns,
  useMetaStatus,
} from "@/lib/api/hooks";
import type { CampaignImportResult } from "@/lib/api/types";

export function ImportMetaCampaignsRoute() {
  const navigate = useNavigate();
  const status = useMetaStatus();
  const query = useImportableCampaigns({
    enabled: Boolean(status.data?.connected),
  });
  const importMutation = useImportCampaigns();

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<CampaignImportResult | null>(null);

  // If the user lands here without a Meta connection, bounce them
  // back to the dashboard (where the Connect Meta card lives).
  if (status.isFetched && !status.data?.connected) {
    return <Navigate to="/dashboard" replace />;
  }

  const quotaUsed = query.data?.quota_used ?? 0;
  const quotaMax = query.data?.quota_max ?? 5;
  const remaining = Math.max(0, quotaMax - quotaUsed);

  const rows = query.data?.importable ?? [];

  const toggle = (metaCampaignId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(metaCampaignId)) {
        next.delete(metaCampaignId);
      } else {
        next.add(metaCampaignId);
      }
      return next;
    });
  };

  const overQuota = selected.size > remaining;
  const canSubmit =
    !importMutation.isPending && selected.size > 0 && !overQuota;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    try {
      const res = await importMutation.mutateAsync({
        meta_campaign_ids: Array.from(selected),
      });
      setResult(res);
      setSelected(new Set());
    } catch {
      /* error surfaced below via mutation state */
    }
  };

  // Once we have a success result, bounce back to the dashboard after
  // a few seconds so the user sees their new campaigns in the grid.
  useEffect(() => {
    if (!result) return;
    if (result.imported.length === 0) return;
    const timer = window.setTimeout(() => {
      navigate("/dashboard");
    }, 2500);
    return () => window.clearTimeout(timer);
  }, [result, navigate]);

  const errorMessage = useMemo(() => {
    const err = query.error ?? importMutation.error;
    if (!err) return null;
    if (err instanceof ApiError) {
      if (err.status === 409) {
        return "Meta isn't connected — reconnect from the dashboard and try again.";
      }
      if (err.status === 400) {
        return "Something about the request was invalid. Refresh and try again.";
      }
    }
    return "Something went wrong loading your campaigns.";
  }, [query.error, importMutation.error]);

  return (
    <div>
      <div className="mb-6">
        <Link
          to="/dashboard"
          className="text-xs text-[var(--accent)] no-underline hover:underline"
        >
          ← Dashboard
        </Link>
        <p className="label mt-2">Import campaigns</p>
        <h1 className="mt-1 text-xl font-medium">
          Pick Meta campaigns to manage
        </h1>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          Selected campaigns will be imported with their current ads as
          baseline variants. You can import up to {quotaMax} campaigns
          total — {quotaUsed} used, {remaining} remaining.
        </p>
      </div>

      {errorMessage && (
        <div
          role="alert"
          className="mb-4 rounded border border-red-700/40 bg-red-950/40 px-3 py-2 text-xs text-red-300"
        >
          {errorMessage}
        </div>
      )}

      {result && (
        <Card className="mb-4">
          <CardHeader>
            <div>
              <CardTitle>Import complete</CardTitle>
              <CardDescription>
                {result.imported.length} imported, {result.failed.length}{" "}
                failed. Redirecting to the dashboard…
              </CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            {result.imported.length > 0 && (
              <ul className="mb-2 list-disc pl-5 text-xs text-[var(--text-secondary)]">
                {result.imported.map((c) => (
                  <li key={c.id}>
                    <span className="font-medium text-[var(--text)]">
                      {c.name}
                    </span>
                    {" — "}
                    {c.registered_deployments} deployment
                    {c.registered_deployments === 1 ? "" : "s"},{" "}
                    {c.seeded_gene_pool_entries} gene pool entries seeded
                  </li>
                ))}
              </ul>
            )}
            {result.failed.length > 0 && (
              <ul className="list-disc pl-5 text-xs text-red-300">
                {result.failed.map((f) => (
                  <li key={f.meta_campaign_id}>
                    <span className="font-mono">{f.meta_campaign_id}</span>:{" "}
                    {f.error}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      {query.isLoading ? (
        <Card>
          <p className="text-sm text-[var(--text-secondary)]">
            Loading campaigns from Meta…
          </p>
        </Card>
      ) : rows.length === 0 ? (
        <Card>
          <p className="text-sm text-[var(--text-secondary)]">
            No campaigns found in your Meta ad account.
          </p>
        </Card>
      ) : (
        <div className="space-y-2">
          {rows.map((row) => (
            <MetaCampaignRow
              key={row.meta_campaign_id}
              campaign={row}
              selected={selected.has(row.meta_campaign_id)}
              onToggle={toggle}
            />
          ))}
        </div>
      )}

      {rows.length > 0 && (
        <div className="mt-6 flex items-center justify-between gap-3">
          <p className="text-xs text-[var(--text-tertiary)]">
            {selected.size} selected
            {overQuota && (
              <span className="ml-2 text-red-300">
                over your {remaining}-campaign quota
              </span>
            )}
          </p>
          <Button
            onClick={handleSubmit}
            disabled={!canSubmit}
            loading={importMutation.isPending}
          >
            Import selected
          </Button>
        </div>
      )}
    </div>
  );
}
