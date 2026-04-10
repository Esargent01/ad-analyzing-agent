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
  importableCampaigns: ["me", "meta", "campaigns"] as const,
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
    staleTime: 60_000,
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
 * Only enabled when the caller has confirmed Meta is connected — this
 * endpoint 409s without a stored connection.
 */
export function useImportableCampaigns(
  options: Omit<
    UseQueryOptions<ImportableCampaignsResponse, ApiError>,
    "queryKey" | "queryFn"
  > = {},
) {
  return useQuery<ImportableCampaignsResponse, ApiError>({
    queryKey: qk.importableCampaigns,
    queryFn: ({ signal }) =>
      api.get<ImportableCampaignsResponse>("/api/me/meta/campaigns", { signal }),
    staleTime: 30_000,
    retry: false,
    ...options,
  });
}

/**
 * Submits the selected campaigns for import. On success we invalidate
 * both the importable-list query (so the cap counter updates + the
 * picker greys out the rows we just imported) and the `me` query (so
 * the sidebar gets the new campaigns).
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
      qc.invalidateQueries({ queryKey: qk.importableCampaigns });
      qc.invalidateQueries({ queryKey: qk.me });
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
