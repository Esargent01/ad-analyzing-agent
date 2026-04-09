/**
 * Hand-rolled response types for Phase 3.
 *
 * These will be replaced by generated types from `types.generated.ts`
 * (produced by `npm run types:generate` against a committed
 * `frontend/openapi.json` snapshot), but having them as a shim means the
 * app builds before the codegen step runs and lets us import a stable
 * name (`types`) from application code regardless of codegen state.
 */

export interface CampaignSummary {
  id: string;
  name: string;
  is_active: boolean;
}

export interface MeResponse {
  id: string;
  email: string;
  campaigns: CampaignSummary[];
}

export interface DailyDatesResponse {
  dates: string[]; // ISO yyyy-mm-dd
}

export interface WeekDescriptor {
  week_start: string;
  week_end: string;
  label: string;
}

export interface WeeklyIndexResponse {
  weeks: WeekDescriptor[];
}

export interface MagicLinkRequest {
  email: string;
}
