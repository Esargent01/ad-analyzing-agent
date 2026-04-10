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

// ---------------------------------------------------------------------------
// Meta OAuth connection (Phase B)
// ---------------------------------------------------------------------------

export interface MetaConnectionStatus {
  connected: boolean;
  meta_user_id: string | null;
  connected_at: string | null;
  token_expires_at: string | null;
}

export interface MetaConnectResponse {
  auth_url: string;
}

// ---------------------------------------------------------------------------
// Campaign import (Phase D)
// ---------------------------------------------------------------------------

export interface ImportableCampaign {
  meta_campaign_id: string;
  name: string;
  status: string;
  daily_budget: number | null;
  created_time: string | null;
  objective: string | null;
  already_imported: boolean;
}

export interface ImportableCampaignsResponse {
  importable: ImportableCampaign[];
  quota_used: number;
  quota_max: number;
}

export interface CampaignImportOverrides {
  daily_budget?: string | number | null;
  max_concurrent_variants?: number | null;
  confidence_threshold?: string | number | null;
}

export interface CampaignImportRequest {
  meta_campaign_ids: string[];
  overrides?: CampaignImportOverrides;
}

export interface ImportedCampaignSummary {
  id: string;
  name: string;
  platform_campaign_id: string;
  daily_budget: string | number;
  seeded_gene_pool_entries: number;
  registered_deployments: number;
}

export interface CampaignImportFailure {
  meta_campaign_id: string;
  error: string;
}

export interface CampaignImportResult {
  imported: ImportedCampaignSummary[];
  failed: CampaignImportFailure[];
  quota_used_after: number;
  quota_max: number;
}

// ---------------------------------------------------------------------------
// Per-user usage / cost rollup (Phase E)
//
// Dollar amounts arrive from Pydantic v2 as JSON strings (Decimal → str)
// so every numeric-looking field here is typed ``string`` and coerced
// through ``Number()`` at render time.
// ---------------------------------------------------------------------------

export interface UsageServiceBreakdown {
  service: string; // "llm" | "meta_api" | "email"
  cost_usd: string;
  calls: number;
}

export interface UsageCampaignBreakdown {
  campaign_id: string | null;
  campaign_name: string | null;
  cost_usd: string;
  calls: number;
}

export interface UsageDayBreakdown {
  day: string; // ISO YYYY-MM-DD
  cost_usd: string;
  calls: number;
}

export interface UsageSummary {
  from_date: string; // ISO YYYY-MM-DD
  to_date: string; // ISO YYYY-MM-DD
  total_cost_usd: string;
  total_calls: number;
  by_service: UsageServiceBreakdown[];
  by_campaign: UsageCampaignBreakdown[];
  by_day: UsageDayBreakdown[];
}

// ---------------------------------------------------------------------------
// Experiments
// ---------------------------------------------------------------------------

export interface ProposedVariant {
  approval_id: string;
  variant_id: string;
  variant_code: string;
  genome: Record<string, string>;
  genome_summary: string;
  hypothesis: string | null;
  submitted_at: string;
  /** "new" | "expiring_soon" */
  classification: string;
  days_until_expiry: number;
}

export interface GenePoolEntry {
  id: string;
  slot_name: string;
  slot_value: string;
  description: string | null;
  source: string | null;
}

export interface ExperimentsResponse {
  proposed_variants: ProposedVariant[];
  gene_pool_by_slot: Record<string, GenePoolEntry[]>;
  allowed_suggestion_slots: string[];
}

export interface ApproveResponse {
  status: string;
  approval_id: string;
}

export interface RejectRequest {
  reason?: string;
}

export interface SuggestRequest {
  slot_name: string;
  slot_value: string;
  description?: string;
}

export interface SuggestResponse {
  status: string;
  slot_name: string;
  slot_value: string;
}

// ---------------------------------------------------------------------------
// Report detail shapes
//
// Decimal fields arrive from the backend as JSON strings by default
// (Pydantic v2 Decimal → string). Every formatter in `lib/format.ts`
// coerces through `Number()` so `string | number | null` here is safe.
// ---------------------------------------------------------------------------

type Num = number | string | null;

// --- Daily report ----------------------------------------------------------

export interface VariantReport {
  variant_id: string;
  variant_code: string;
  genome: Record<string, string>;
  genome_summary: string;
  hypothesis: string | null;
  /** "winner" | "steady" | "new" | "fatigue" | "paused" */
  status: string;
  days_active: number;

  // Primary
  spend: Num;
  purchases: number;
  purchase_value: Num;
  cost_per_purchase: Num;
  roas: Num;

  // Diagnostic
  impressions: number;
  reach: number;
  video_views_3s: number;
  video_views_15s: number;
  link_clicks: number;
  landing_page_views: number;
  add_to_carts: number;

  // Computed rates (0-100 scale)
  hook_rate_pct: number;
  hold_rate_pct: number;
  ctr_pct: number;
  atc_rate_pct: number;
  checkout_rate_pct: number;
  frequency: number;
}

export interface ReportFunnelStage {
  label: string;
  count: number;
  rate_pct: number;
  rate_label: string;
  dropoff_pct: number;
  bar_color: string;
}

export interface Diagnostic {
  text: string;
  /** "good" | "warning" | "bad" */
  severity: string;
}

export interface FatigueAlert {
  variant_code: string;
  reason: string;
  recommendation: string;
}

export interface ReportCycleAction {
  action_type: string;
  variant_code: string;
  details: string | null;
}

export interface NextCyclePreview {
  hypothesis: string;
  genome_summary: string;
}

export interface DailyReport {
  campaign_name: string;
  campaign_id: string;
  cycle_number: number;
  report_date: string; // ISO YYYY-MM-DD
  day_number: number;

  total_spend: Num;
  total_purchases: number;
  avg_cost_per_purchase: Num;
  avg_roas: Num;
  avg_hook_rate_pct: number;

  prev_spend: Num;
  prev_purchases: number | null;
  prev_avg_cpa: Num;
  prev_avg_roas: Num;

  variants: VariantReport[];

  best_variant: VariantReport | null;
  best_variant_funnel: ReportFunnelStage[];
  best_variant_diagnostics: Diagnostic[];
  best_variant_projection: string | null;

  fatigue_alerts: FatigueAlert[];
  actions: ReportCycleAction[];
  next_cycle: NextCyclePreview[];

  winners: VariantReport[];
}

// --- Weekly report ---------------------------------------------------------

export interface VariantSummary {
  variant_id: string;
  variant_code: string;
  status: string;
  impressions: number;
  clicks: number;
  conversions: number;
  spend: Num;
  ctr: Num;
  cpa: Num;

  reach: number;
  video_views_3s: number;
  video_views_15s: number;
  thruplays: number;
  link_clicks: number;
  landing_page_views: number;
  add_to_carts: number;
  purchases: number;
  purchase_value: Num;
  hook_rate: Num;
  hold_rate: Num;
  cost_per_purchase: Num;
  roas: Num;
}

export interface FunnelStage {
  stage_name: string;
  value: number;
  rate: Num;
  cost_per: Num;
}

export interface ElementInsight {
  slot_name: string;
  slot_value: string;
  variants_tested: number;
  avg_ctr: Num;
  avg_cpa: Num;
  best_ctr: Num;
  worst_ctr: Num;
  total_impressions: number;
  total_conversions: number;
  confidence: Num;

  avg_hook_rate: Num;
  avg_roas: Num;
  best_hook_rate: Num;
  best_cpa: Num;
  total_purchases: number;
}

export interface InteractionInsight {
  slot_a_name: string;
  slot_a_value: string;
  slot_b_name: string;
  slot_b_value: string;
  variants_tested: number;
  combined_avg_ctr: Num;
  solo_a_avg_ctr: Num;
  solo_b_avg_ctr: Num;
  interaction_lift: Num;
  confidence: Num;
}

export interface WeeklyReport {
  campaign_id: string;
  campaign_name: string;
  week_start: string;
  week_end: string;

  total_spend: Num;
  total_impressions: number;
  total_clicks: number;
  total_conversions: number;
  avg_ctr: Num;
  avg_cpa: Num;

  total_reach: number;
  total_video_views_3s: number;
  total_video_views_15s: number;
  total_thruplays: number;
  total_link_clicks: number;
  total_landing_page_views: number;
  total_add_to_carts: number;
  total_purchases: number;
  total_purchase_value: Num;
  avg_hook_rate: Num;
  avg_hold_rate: Num;
  avg_cpm: Num;
  avg_frequency: Num;
  avg_roas: Num;
  avg_cost_per_purchase: Num;

  funnel_stages: FunnelStage[];

  best_variant: VariantSummary | null;
  worst_variant: VariantSummary | null;
  all_variants: VariantSummary[];

  top_elements: ElementInsight[];
  top_interactions: InteractionInsight[];

  cycles_run: number;
  variants_launched: number;
  variants_retired: number;
  summary_text: string;

  proposed_variants: ProposedVariant[];
  expired_count: number;
  generation_paused: boolean;
  review_url: string | null;
}
