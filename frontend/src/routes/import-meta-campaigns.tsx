/**
 * Phase D + Phase G self-serve import page.
 *
 * Flow:
 * 1. Resolve the effective ad account (explicit pick → default → prompt)
 * 2. Fetch the connected user's Meta campaigns scoped to that account
 *    (`useImportableCampaigns`)
 * 3. Render one `<MetaCampaignRow />` per result with checkboxes
 * 4. Submit the selected IDs + picked account/Page/landing URL via
 *    `useImportCampaigns`
 * 5. On success, show the per-campaign result (imported / failed)
 *    and redirect back to the dashboard after a short beat
 *
 * Phase G additions:
 * - The top of the page carries an account dropdown (hidden when the
 *   user has exactly one account) and a Page dropdown (same rule).
 *   Switching accounts refetches the campaign list scoped to the new
 *   account — each account is cached under its own query key.
 * - A single landing page URL input is shared across all campaigns in
 *   the current import batch. Optional; the backend accepts null.
 * - If the backend returns 400 ``pick_account_first`` we show the
 *   account dropdown prominently and block the submit button until a
 *   choice is made.
 * - The submit body carries ``ad_account_id`` + ``page_id`` +
 *   ``landing_page_url`` as required Phase G fields. Without them the
 *   backend hard-fails with ``account_not_in_allowlist``.
 *
 * Guardrails:
 * - If Meta is not connected, redirect to /dashboard (the card there
 *   handles the connect flow)
 * - The submit button is disabled when the selection would push the
 *   user over `quota_max`, when no Page is chosen, or when no account
 *   has been picked yet
 * - Already-imported rows are locked via `MetaCampaignRow`'s disabled
 *   prop
 */

import { useEffect, useMemo, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";

import { MetaCampaignRow } from "@/components/MetaCampaignRow";
import { DashPage } from "@/components/dashboard/DashPage";
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

  // Phase G: the selected ad account drives the query. Start with
  // the user's default if they have one; otherwise leave null and
  // let the account dropdown force a choice.
  const [adAccountId, setAdAccountId] = useState<string | null>(null);

  // Seed the account/page selection once the connection status comes
  // back so single-account users don't see an empty state. Defend
  // against an older backend whose ``/api/me/meta/status`` payload
  // doesn't yet carry the Phase G fields — the `?? []` keeps the
  // length check from crashing on undefined during a staggered deploy.
  useEffect(() => {
    if (!status.data?.connected) return;
    if (adAccountId) return;
    const accounts = status.data.available_ad_accounts ?? [];
    const defaultAccount =
      status.data.default_ad_account_id ??
      (accounts.length === 1 ? accounts[0].id : null);
    if (defaultAccount) setAdAccountId(defaultAccount);
  }, [status.data, adAccountId]);

  const query = useImportableCampaigns(adAccountId, {
    enabled: Boolean(status.data?.connected && adAccountId),
  });
  const importMutation = useImportCampaigns();

  // The picker payload (when loaded) carries the available accounts +
  // pages so we don't need a second roundtrip — prefer it over the
  // ``useMetaStatus`` copy so any refetch keeps us in sync.
  const availableAccounts =
    query.data?.available_ad_accounts ??
    status.data?.available_ad_accounts ??
    [];
  const availablePages =
    query.data?.available_pages ?? status.data?.available_pages ?? [];
  const defaultPageId =
    query.data?.default_page_id ?? status.data?.default_page_id ?? null;

  // Page selection — mirror the account logic.
  const [pageId, setPageId] = useState<string | null>(null);
  useEffect(() => {
    if (pageId) return;
    if (defaultPageId) {
      setPageId(defaultPageId);
      return;
    }
    if (availablePages.length === 1) {
      setPageId(availablePages[0].id);
    }
  }, [defaultPageId, availablePages, pageId]);

  const [landingPageUrl, setLandingPageUrl] = useState<string>("");

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
    !importMutation.isPending &&
    selected.size > 0 &&
    !overQuota &&
    Boolean(adAccountId) &&
    Boolean(pageId);

  const handleSubmit = async () => {
    if (!canSubmit || !adAccountId || !pageId) return;
    try {
      const res = await importMutation.mutateAsync({
        meta_campaign_ids: Array.from(selected),
        ad_account_id: adAccountId,
        page_id: pageId,
        landing_page_url: landingPageUrl.trim() || null,
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
        // Phase G: the server may be telling us to pick an account
        // first (``pick_account_first``) or that we tried to use an
        // account / Page that isn't in the allowlist
        // (``account_not_in_allowlist``). FastAPI serialises
        // HTTPException(status_code=400, detail="...") into
        // ``{"detail": "..."}``, which the client wrapper stores on
        // ``ApiError.detail`` (the whole JSON body, not just the
        // string). Peel the inner ``.detail`` off.
        const raw = err.detail;
        let code: string | undefined;
        if (typeof raw === "string") {
          code = raw;
        } else if (raw && typeof raw === "object" && "detail" in raw) {
          const inner = (raw as { detail?: unknown }).detail;
          if (typeof inner === "string") code = inner;
        }
        if (code === "pick_account_first") {
          return "Pick an ad account above before fetching campaigns.";
        }
        if (code === "account_not_in_allowlist") {
          return "That ad account or Page isn't in your connected Meta assets. Refresh and try again.";
        }
        return "Something about the request was invalid. Refresh and try again.";
      }
    }
    return "Something went wrong loading your campaigns.";
  }, [query.error, importMutation.error]);

  const showAccountPicker = availableAccounts.length > 1;
  const showPagePicker = availablePages.length > 1;

  // Guardrail: importing a Meta campaign requires a ``page_id`` on the
  // backend (``src/services/campaign_import.py``). If the connected
  // user's OAuth token didn't grant ``pages_show_list``, the callback
  // cached ``available_pages=[]`` and nothing will ever satisfy the
  // submit gate. Surface a specific, actionable error instead of
  // silently disabling the button.
  const missingPagesAccess =
    Boolean(status.data?.connected) && availablePages.length === 0;

  return (
    <DashPage
      crumb={[
        { label: "Dashboard", href: "/dashboard" },
        { label: "Import campaigns" },
      ]}
      title="import campaigns"
      sub={
        <>
          pick meta campaigns to manage · you can import up to {quotaMax} total
          — {quotaUsed} used, {remaining} remaining.
        </>
      }
    >

      {(showAccountPicker || showPagePicker) && (
        <Panel
          title="Meta tenancy"
          description="Pick which ad account and Page each imported campaign should run against."
          className="mb-4"
        >
          <div
            data-ds-grid
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 12,
            }}
          >
            {showAccountPicker && (
              <PickerField label="Ad account">
                <select
                  value={adAccountId ?? ""}
                  onChange={(e) => setAdAccountId(e.target.value || null)}
                  className="ds-input"
                >
                  <option value="">— pick one —</option>
                  {availableAccounts.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name} ({a.id})
                    </option>
                  ))}
                </select>
              </PickerField>
            )}
            {showPagePicker && (
              <PickerField label="Page">
                <select
                  value={pageId ?? ""}
                  onChange={(e) => setPageId(e.target.value || null)}
                  className="ds-input"
                >
                  <option value="">— pick one —</option>
                  {availablePages.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.category})
                    </option>
                  ))}
                </select>
              </PickerField>
            )}
          </div>
        </Panel>
      )}

      <Panel
        title="Landing page URL"
        description="Optional — applied to every campaign in this import batch. You can change it per campaign later from the dashboard."
        className="mb-4"
      >
        <input
          type="url"
          value={landingPageUrl}
          onChange={(e) => setLandingPageUrl(e.target.value)}
          placeholder="https://shop.example.com/spring"
          className="ds-input"
        />
      </Panel>

      {errorMessage && (
        <BannerAlert tone="error">{errorMessage}</BannerAlert>
      )}

      {missingPagesAccess && (
        <BannerAlert tone="warning">
          Your Meta connection doesn&apos;t have access to any Pages, so we
          can&apos;t import a campaign (every imported campaign needs a
          Page to run ads from).{" "}
          <Link
            to="/dashboard"
            style={{
              color: "inherit",
              textDecoration: "underline",
              textUnderlineOffset: 2,
            }}
          >
            Disconnect and reconnect Meta from the dashboard
          </Link>{" "}
          — when the consent screen appears, make sure the Pages
          permission is granted.
        </BannerAlert>
      )}

      {result && (
        <Panel
          title="Import complete"
          description={`${result.imported.length} imported, ${result.failed.length} failed. Redirecting to the dashboard…`}
          className="mb-4"
        >
          {result.imported.length > 0 && (
            <ul
              style={{
                margin: 0,
                paddingLeft: 18,
                fontSize: 13,
                color: "var(--ink-2)",
                lineHeight: 1.6,
              }}
            >
              {result.imported.map((c) => (
                <li key={c.id}>
                  <span style={{ fontWeight: 500, color: "var(--ink)" }}>
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
            <ul
              style={{
                margin: "8px 0 0",
                paddingLeft: 18,
                fontSize: 12.5,
                color: "oklch(45% 0.16 28)",
                lineHeight: 1.6,
              }}
            >
              {result.failed.map((f) => (
                <li key={f.meta_campaign_id}>
                  <span style={{ fontFamily: "var(--font-mono)" }}>
                    {f.meta_campaign_id}
                  </span>
                  : {f.error}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      )}

      {!adAccountId ? (
        <ZeroStatePanel>
          Pick an ad account above to load its campaigns.
        </ZeroStatePanel>
      ) : query.isLoading ? (
        <ZeroStatePanel>Loading campaigns from Meta…</ZeroStatePanel>
      ) : rows.length === 0 ? (
        <ZeroStatePanel>
          {availableAccounts.length === 0
            ? "Your Meta token has no reachable ad accounts. Create one in Meta Ads Manager, then reconnect."
            : "No campaigns found in the selected ad account."}
        </ZeroStatePanel>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: 24,
            padding: "16px 20px",
            borderRadius: 12,
            background: "var(--ink)",
            color: "var(--paper)",
            flexWrap: "wrap",
            gap: 12,
          }}
        >
          <div style={{ fontSize: 13.5 }}>
            <b>{selected.size}</b> campaigns selected
            {overQuota && (
              <span
                style={{
                  marginLeft: 10,
                  color: "oklch(78% 0.14 28)",
                }}
              >
                — over your {remaining}-campaign quota
              </span>
            )}
            {!pageId && !missingPagesAccess && (
              <span
                style={{
                  marginLeft: 10,
                  color: "oklch(78% 0.14 28)",
                }}
              >
                — pick a Page above before importing
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="btn btn-accent btn-sm"
          >
            {importMutation.isPending
              ? "Importing…"
              : selected.size > 0
                ? `Import ${selected.size} →`
                : "Import selected"}
          </button>
        </div>
      )}
    </DashPage>
  );
}

/* ---------------------------------------------------------------- */
/* Local components — warm-paper panels replacing the legacy Card.  */
/* ---------------------------------------------------------------- */

function Panel({
  title,
  description,
  className,
  children,
}: {
  title: string;
  description?: string;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className={className}
      style={{
        padding: 20,
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "white",
      }}
    >
      <h3
        style={{
          fontSize: 14,
          fontWeight: 500,
          color: "var(--ink)",
          margin: 0,
          letterSpacing: "-0.01em",
        }}
      >
        {title}
      </h3>
      {description && (
        <p
          style={{
            margin: "4px 0 14px",
            fontSize: 12.5,
            color: "var(--muted)",
            lineHeight: 1.5,
          }}
        >
          {description}
        </p>
      )}
      {children}
    </div>
  );
}

function PickerField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <span className="eyebrow" style={{ fontSize: 10 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

function BannerAlert({
  tone,
  children,
}: {
  tone: "error" | "warning";
  children: React.ReactNode;
}) {
  const style =
    tone === "error"
      ? {
          border: "1px solid oklch(88% 0.08 28)",
          background: "oklch(98% 0.02 28)",
          color: "oklch(40% 0.16 28)",
        }
      : {
          border: "1px solid oklch(88% 0.09 75)",
          background: "oklch(98% 0.03 75)",
          color: "oklch(42% 0.15 65)",
        };
  return (
    <div
      role="alert"
      className="mb-4"
      style={{
        padding: "12px 14px",
        borderRadius: 10,
        fontSize: 13,
        lineHeight: 1.55,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

function ZeroStatePanel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        padding: 24,
        border: "1px dashed var(--border)",
        borderRadius: 12,
        background: "var(--paper-2)",
        fontSize: 13.5,
        color: "var(--muted)",
        textAlign: "center",
      }}
    >
      {children}
    </div>
  );
}
