/**
 * TanStack Query hooks — single source of truth for server state.
 *
 * Keep the hook list flat in Phase 3. As we add routes in Phases 4-6,
 * new hooks get appended here; callers only ever import from this file.
 */

import { useMutation, useQuery, type UseQueryOptions } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api/client";
import type {
  DailyDatesResponse,
  MagicLinkRequest,
  MeResponse,
  WeeklyIndexResponse,
} from "@/lib/api/types";

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const qk = {
  me: ["me"] as const,
  dailyDates: (campaignId: string) =>
    ["campaigns", campaignId, "reports", "daily"] as const,
  weeklyIndex: (campaignId: string) =>
    ["campaigns", campaignId, "reports", "weekly"] as const,
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
