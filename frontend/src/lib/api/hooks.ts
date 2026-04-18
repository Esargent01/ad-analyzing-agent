/**
 * TanStack Query hooks — single source of truth for server state.
 *
 * Keep the hook list flat in Phase 3. As we add routes in Phases 4-6,
 * new hooks get appended here; callers only ever import from this file.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api/client";
import type {
  ApproveResponse,
  CampaignImportRequest,
  CampaignImportResult,
  DailyDatesResponse,
  DailyReport,
  ExperimentsResponse,
  ImportableCampaignsResponse,
  MagicLinkRequest,
  MeResponse,
  MetaConnectResponse,
  MetaConnectionStatus,
  SuggestRequest,
  SuggestResponse,
  UsageSummary,
  WeeklyIndexResponse,
  WeeklyReport,
} from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const qk = {
  me: ["me"] as const,
  metaStatus: ["me", "meta", "status"] as const,
  // Phase G: campaigns are scoped by ad account, so the cache key
  // must include the selected account id so different picks don't
  // clobber each other.
  importableCampaigns: (adAccountId?: string | null) =>
    ["me", "meta", "campaigns", adAccountId ?? "default"] as const,
  myUsage: (fromDate?: string, toDate?: string) =>
    ["me", "usage", fromDate ?? "default", toDate ?? "default"] as const,
  dailyDates: (campaignId: string) =>
    ["campaigns", campaignId, "reports", "daily"] as const,
  dailyReport: (campaignId: string, reportDate: string) =>
    ["campaigns", campaignId, "reports", "daily", reportDate] as const,
  weeklyIndex: (campaignId: string) =>
    ["campaigns", campaignId, "reports", "weekly"] as const,
  weeklyReport: (campaignId: string, weekStart: string) =>
    ["campaigns", campaignId, "reports", "weekly", weekStart] as const,
  experiments: (campaignId: string) =>
    ["campaigns", campaignId, "experiments"] as const,
};

// ---------------------------------------------------------------------------
// Auth + session
// ---------------------------------------------------------------------------

export function useMe(
  options: Omit<
    UseQueryOptions<MeResponse | null, ApiError>,
    "queryKey" | "queryFn"
  > = {},
) {
  return useQuery<MeResponse | null, ApiError>({
    queryKey: qk.me,
    queryFn: async ({ signal }) => {
      try {
        return await api.get<MeResponse>("/api/me", {
          signal,
          suppressAuthRedirect: true,
        });
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          return null;
        }
        throw err;
      }
    },
    staleTime: 60_000,
    retry: false,
    ...options,
  });
}

export function useSendMagicLink() {
  return useMutation<void, ApiError, MagicLinkRequest>({
    mutationFn: async ({ email }) => {
      await api.post<void>("/api/auth/magic-link", { email });
    },
  });
}

export function useLogout() {
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      await api.post<void>("/api/auth/logout");
    },
  });
}

// ---------------------------------------------------------------------------
// Meta OAuth connection (Phase B)
// ---------------------------------------------------------------------------

/**
 * Polls the backend for whether the signed-in user has a stored Meta
 * connection. Cheap to call; re-run when the page regains focus so the
 * UI flips from "Connect" to "Connected" immediately after the OAuth
 * callback lands.
 */
export function useMetaStatus(
  options: Omit<
    UseQueryOptions<MetaConnectionStatus, ApiError>,
    "queryKey" | "queryFn"
  > = {},
) {
  return useQuery<MetaConnectionStatus, ApiError>({
    queryKey: qk.metaStatus,
    queryFn: ({ signal }) =>
      api.get<MetaConnectionStatus>("/api/me/meta/status", { signal }),
    // Connection state is stable per session; re-check only if the user
    // disconnects explicitly (the disconnect mutation invalidates this
    // query directly).
    staleTime: 5 * 60_000,
    ...options,
  });
}

/**
 * Starts the OAuth dance. Caller should `window.location.href` the
 * returned `auth_url` — Facebook will bounce back to the callback
 * endpoint, which 302s to `/dashboard?meta_connected=1`.
 */
export function useConnectMeta() {
  return useMutation<MetaConnectResponse, ApiError, void>({
    mutationFn: () => api.post<MetaConnectResponse>("/api/me/meta/connect"),
  });
}

/**
 * Drops the stored encrypted token. Invalidates the status query so
 * the card flips back to the unconnected state.
 */
export function useDisconnectMeta() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: () => api.delete<void>("/api/me/meta/connection"),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.metaStatus });
    },
  });
}

// ---------------------------------------------------------------------------
// Meta campaign import (Phase D)
// ---------------------------------------------------------------------------

/**
 * Fetches the list of campaigns the connected user has in their Meta
 * ad account, with a flag for anything already imported. Also surfaces
 * the user's current cap usage so the picker can render a "3/5 used"
 * widget.
 *
 * Phase G: takes an optional ``adAccountId``. If passed, the query
 * scopes to that account (and is cached separately in TanStack Query
 * via the per-account query key). If omitted, the server falls back
 * to the user's ``default_ad_account_id``; if that's also null the
 * server returns 400 ``pick_account_first`` and the UI must force a
 * choice from the account dropdown.
 *
 * Only enabled when the caller has confirmed Meta is connected — this
 * endpoint 409s without a stored connection.
 */
export function useImportableCampaigns(
  adAccountId: string | null = null,
  options: Omit<
    UseQueryOptions<ImportableCampaignsResponse, ApiError>,
    "queryKey" | "queryFn"
  > = {},
) {
  const path = adAccountId
    ? `/api/me/meta/campaigns?ad_account_id=${encodeURIComponent(adAccountId)}`
    : "/api/me/meta/campaigns";
  return useQuery<ImportableCampaignsResponse, ApiError>({
    queryKey: qk.importableCampaigns(adAccountId),
    queryFn: ({ signal }) =>
      api.get<ImportableCampaignsResponse>(path, { signal }),
    staleTime: 30_000,
    retry: false,
    ...options,
  });
}

/**
 * Submits the selected campaigns for import. On success we invalidate
 * both the importable-list queries (so the cap counter updates + the
 * picker greys out the rows we just imported — all account variants
 * are flushed) and the `me` query (so the sidebar gets the new
 * campaigns).
 *
 * Phase G: the body now carries ``ad_account_id`` + ``page_id`` +
 * optional ``landing_page_url``. All three are per-import choices the
 * UI collects from the account/Page/URL widgets.
 */
export function useImportCampaigns() {
  const qc = useQueryClient();
  return useMutation<CampaignImportResult, ApiError, CampaignImportRequest>({
    mutationFn: (body) =>
      api.post<CampaignImportResult>(
        "/api/me/meta/campaigns/import",
        body as unknown as Record<string, unknown>,
      ),
    onSuccess: () => {
      // Invalidate every per-account variant of the importable list.
      qc.invalidateQueries({ queryKey: ["me", "meta", "campaigns"] });
      qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

/**
 * Deletes a campaign and every row owned by it (variants, deployments,
 * metrics, test cycles, element rollups, media). Destructive and
 * permanent — the caller is responsible for confirming intent.
 *
 * On success, invalidates the ``me`` query so the dashboard grid
 * drops the campaign tile on next render, and the importable list
 * so the freshly-freed ``platform_campaign_id`` becomes available
 * to re-import.
 */
export function useDeleteCampaign() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, string>({
    mutationFn: (campaignId) =>
      api.delete<void>(`/api/campaigns/${campaignId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.me });
      qc.invalidateQueries({ queryKey: ["me", "meta", "campaigns"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Per-user usage rollup (Phase E)
// ---------------------------------------------------------------------------

export interface UsageRange {
  /** ISO YYYY-MM-DD — defaults to 30 days ago on the server. */
  from?: string;
  /** ISO YYYY-MM-DD — defaults to today on the server. */
  to?: string;
}

/**
 * Fetches the signed-in user's cost/call rollup for the given window.
 * Omit ``from``/``to`` to get the backend default (trailing 30 days).
 */
export function useMyUsage(
  range: UsageRange = {},
  options: Omit<
    UseQueryOptions<UsageSummary, ApiError>,
    "queryKey" | "queryFn"
  > = {},
) {
  const search = new URLSearchParams();
  if (range.from) search.set("from", range.from);
  if (range.to) search.set("to", range.to);
  const qs = search.toString();
  const path = qs ? `/api/me/usage?${qs}` : "/api/me/usage";

  return useQuery<UsageSummary, ApiError>({
    queryKey: qk.myUsage(range.from, range.to),
    queryFn: ({ signal }) => api.get<UsageSummary>(path, { signal }),
    staleTime: 60_000,
    ...options,
  });
}

// ---------------------------------------------------------------------------
// Campaign report indexes (used by Phase 4 routes, surfaced here early so
// the dashboard home can prefetch counts if needed)
// ---------------------------------------------------------------------------

export function useDailyDates(campaignId: string | undefined) {
  return useQuery<DailyDatesResponse, ApiError>({
    queryKey: campaignId ? qk.dailyDates(campaignId) : ["daily-dates-disabled"],
    queryFn: ({ signal }) =>
      api.get<DailyDatesResponse>(
        `/api/campaigns/${campaignId}/reports/daily`,
        { signal },
      ),
    enabled: Boolean(campaignId),
    // Index shifts at most once per cycle (one-a-day); 2 min keeps
    // in-session navigation instant without hiding newly-run reports
    // for long.
    staleTime: 2 * 60_000,
  });
}

export function useWeeklyIndex(campaignId: string | undefined) {
  return useQuery<WeeklyIndexResponse, ApiError>({
    queryKey: campaignId ? qk.weeklyIndex(campaignId) : ["weekly-index-disabled"],
    queryFn: ({ signal }) =>
      api.get<WeeklyIndexResponse>(
        `/api/campaigns/${campaignId}/reports/weekly`,
        { signal },
      ),
    enabled: Boolean(campaignId),
    staleTime: 2 * 60_000,
  });
}

// ---------------------------------------------------------------------------
// Individual report detail fetches
// ---------------------------------------------------------------------------

export function useDailyReport(
  campaignId: string | undefined,
  reportDate: string | undefined,
) {
  const enabled = Boolean(campaignId && reportDate);
  return useQuery<DailyReport, ApiError>({
    queryKey:
      campaignId && reportDate
        ? qk.dailyReport(campaignId, reportDate)
        : ["daily-report-disabled"],
    queryFn: ({ signal }) =>
      api.get<DailyReport>(
        `/api/campaigns/${campaignId}/reports/daily/${reportDate}`,
        { signal },
      ),
    enabled,
    // Keep the previous date's report on-screen while the new one
    // fetches so switching dates doesn't flash a skeleton.
    placeholderData: (prev) => prev,
  });
}

export function useWeeklyReport(
  campaignId: string | undefined,
  weekStart: string | undefined,
) {
  const enabled = Boolean(campaignId && weekStart);
  return useQuery<WeeklyReport, ApiError>({
    queryKey:
      campaignId && weekStart
        ? qk.weeklyReport(campaignId, weekStart)
        : ["weekly-report-disabled"],
    queryFn: ({ signal }) =>
      api.get<WeeklyReport>(
        `/api/campaigns/${campaignId}/reports/weekly/${weekStart}`,
        { signal },
      ),
    enabled,
    placeholderData: (prev) => prev,
  });
}

// ---------------------------------------------------------------------------
// Experiments (proposed variants, gene pool, pending approvals)
// ---------------------------------------------------------------------------

export function useExperiments(campaignId: string | undefined) {
  return useQuery<ExperimentsResponse, ApiError>({
    queryKey: campaignId ? qk.experiments(campaignId) : ["experiments-disabled"],
    queryFn: ({ signal }) =>
      api.get<ExperimentsResponse>(
        `/api/campaigns/${campaignId}/experiments`,
        { signal },
      ),
    enabled: Boolean(campaignId),
  });
}

// ---------------------------------------------------------------------------
// Experiment mutations
// ---------------------------------------------------------------------------

/**
 * Approve a pending proposal. On success we invalidate the
 * `experiments` query so the card fades out and the count drops.
 */
export function useApproveProposal(campaignId: string) {
  const qc = useQueryClient();
  return useMutation<ApproveResponse, ApiError, string>({
    mutationFn: (approvalId) =>
      api.post<ApproveResponse>(
        `/api/campaigns/${campaignId}/experiments/${approvalId}/approve`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.experiments(campaignId) });
    },
  });
}

export interface RejectProposalVars {
  approvalId: string;
  reason?: string;
}

export function useRejectProposal(campaignId: string) {
  const qc = useQueryClient();
  return useMutation<ApproveResponse, ApiError, RejectProposalVars>({
    mutationFn: ({ approvalId, reason }) =>
      api.post<ApproveResponse>(
        `/api/campaigns/${campaignId}/experiments/${approvalId}/reject`,
        { reason: reason ?? "user_rejected" },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: qk.experiments(campaignId) });
    },
  });
}

export function useSuggestGenome(campaignId: string) {
  const qc = useQueryClient();
  return useMutation<SuggestResponse, ApiError, SuggestRequest>({
    mutationFn: (body) =>
      api.post<SuggestResponse>(
        `/api/campaigns/${campaignId}/experiments/suggest`,
        body as unknown as Record<string, unknown>,
      ),
    onSuccess: () => {
      // The gene pool is returned as part of the experiments response,
      // so refetching the experiments query keeps everything in sync.
      qc.invalidateQueries({ queryKey: qk.experiments(campaignId) });
    },
  });
}
