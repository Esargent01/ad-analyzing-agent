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
// Meta OAuth connection (Phase B + Phase G)
// ---------------------------------------------------------------------------

export interface MetaAdAccountInfo {
  id: string;
  name: string;
  account_status: number;
  currency: string;
}

export interface MetaPageInfo {
  id: string;
  name: string;
  category: string;
}

export interface MetaConnectionStatus {
  connected: boolean;
  meta_user_id: string | null;
  connected_at: string | null;
  token_expires_at: string | null;
  /** Phase G: ad accounts reachable by the user's token. */
  available_ad_accounts: MetaAdAccountInfo[];
  /** Phase G: Pages reachable by the user's token. */
  available_pages: MetaPageInfo[];
  /** Phase G: auto-picked default when there's exactly one ad account. */
  default_ad_account_id: string | null;
  /** Phase G: auto-picked default when there's exactly one Page. */
  default_page_id: string | null;
}

export interface MetaConnectResponse {
  auth_url: string;
}

// ---------------------------------------------------------------------------
// Campaign import (Phase D + Phase G)
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
  /** Phase G: the user's full account allowlist (mirrors
   * ``MetaConnectionStatus.available_ad_accounts``) so the import page
   * can render the account picker from a single roundtrip. */
  available_ad_accounts: MetaAdAccountInfo[];
  available_pages: MetaPageInfo[];
  default_ad_account_id: string | null;
  default_page_id: string | null;
  /** Phase G: the ad account the returned ``importable`` list was
   * scoped to — either the explicit query param or the default. */
  selected_ad_account_id: string | null;
}

export interface CampaignImportOverrides {
  daily_budget?: string | number | null;
  max_concurrent_variants?: number | null;
  confidence_threshold?: string | number | null;
}

export interface CampaignImportRequest {
  meta_campaign_ids: string[];
  /** Phase G: the ad account to pin each imported campaign to.
   * Required — must be in the user's ``available_ad_accounts``. */
  ad_account_id: string;
  /** Phase G: the Page to pin each imported campaign to.
   * Required — must be in the user's ``available_pages``. */
  page_id: string;
  /** Phase G: free-text landing page URL per import batch.
   * Optional — leave null to skip. */
  landing_page_url?: string | null;
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

// ---------------------------------------------------------------------------
// Phase H: discriminated union for the experiments page.
//
// The backend returns a single ``pending_approvals`` list where every
// item carries a literal ``kind`` tag so the frontend can render the
// right card without inspecting payload shapes. Pause and scale cards
// don't own a ``variant_id``; new_variant rows keep the pre-Phase-H
// fields on ``PendingNewVariant``.
// ---------------------------------------------------------------------------

export interface PauseEvidence {
  reason: "statistically_significant_loser" | "audience_fatigue";
  variant_ctr?: number | null;
  baseline_ctr?: number | null;
  p_value?: number | null;
  z_score?: number | null;
  impressions?: number | null;
  clicks?: number | null;
  consecutive_decline_days?: number | null;
  trend_slope?: number | null;
}

export interface ScaleEvidence {
  allocation_method?: string;
  impressions?: number | null;
  clicks?: number | null;
  posterior_mean?: number | null;
  share_of_allocation?: number | null;
}

export interface PendingNewVariant {
  kind: "new_variant";
  approval_id: string;
  variant_id: string | null;
  variant_code: string;
  genome: Record<string, string>;
  genome_summary: string;
  hypothesis: string | null;
  submitted_at: string;
  classification: string; // "new" | "expiring_soon"
  days_until_expiry: number;
}

export interface PendingPauseVariant {
  kind: "pause_variant";
  approval_id: string;
  campaign_id: string;
  deployment_id: string;
  platform_ad_id: string;
  variant_code: string | null;
  genome_snapshot: Record<string, string>;
  reason: "statistically_significant_loser" | "audience_fatigue";
  evidence: PauseEvidence;
  submitted_at: string;
}

export interface PendingScaleBudget {
  kind: "scale_budget";
  approval_id: string;
  campaign_id: string;
  deployment_id: string;
  platform_ad_id: string;
  variant_code: string | null;
  genome_snapshot: Record<string, string>;
  current_budget: string | number;
  proposed_budget: string | number;
  reason: string;
  evidence: ScaleEvidence;
  submitted_at: string;
}

export interface PendingPromoteWinner {
  kind: "promote_winner";
  approval_id: string;
  variant_id: string | null;
  variant_code: string;
  submitted_at: string;
}

export type PendingApproval =
  | PendingNewVariant
  | PendingPauseVariant
  | PendingScaleBudget
  | PendingPromoteWinner;

export interface ExperimentsResponse {
  /** Phase H: back-compat subset — still populated for any consumer
   * that hasn't switched to the discriminated union yet. */
  proposed_variants: ProposedVariant[];
  /** Phase H: unified discriminated union — new_variant + pause +
   * scale + promote. Sorted server-side pause → scale → new_variant. */
  pending_approvals: PendingApproval[];
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
  /**
   * Creative format: "video" | "image" | "mixed" | "unknown". Sourced
   * from ``variants.media_type`` which mirrors Meta's
   * ``AdCreative.object_type``. Used by the dashboard to hide
   * video-only metrics (hook rate, hold rate) on image ads.
   */
  media_type: string;

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

  // Objective-specific counts + derived metrics (post PR 2).
  leads: number;
  post_engagements: number;
  cost_per_lead: number | null;
  cost_per_engagement: number | null;
  engagement_rate_pct: number;
  cpc: number | null;
  cpm: number;
}

// --- Objective-aware display view-models ---------------------------------
// These mirror the Pydantic models in src/models/reports.py and are
// built server-side per the campaign's Meta objective. Both the daily
// and weekly reports carry lists of these so the React components can
// iterate without branching on objective themselves.

export interface HeadlineMetric {
  label: string;
  value: string;
  sub: string | null;
  tone: "good" | "bad" | "neutral";
}

export interface SummaryNumber {
  label: string;
  value: string;
  tone: "good" | "bad" | "neutral";
}

export interface DiagnosticTile {
  label: string;
  value: string;
  benchmark: string | null;
  tone: "good" | "bad" | "neutral";
}

export interface VariantTableColumn {
  label: string;
  /** Attr name on VariantReport / VariantSummary. */
  key: string;
  /** Format code: ``currency`` | ``int_comma`` | ``int`` | ``pct`` |
   *  ``roas`` | ``onedecimal``. */
  fmt: string;
  /** When true, image-media variants render ``—`` instead of the raw
   *  value (the Hook-rate convention). */
  image_em_dash: boolean;
}

export interface WeeklyMetricRow {
  title: string;
  cards: HeadlineMetric[];
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
  /** Canonical ODAX objective. Drives the display lists below. */
  objective: string;

  total_spend: Num;
  total_purchases: number;
  avg_cost_per_purchase: Num;
  avg_roas: Num;
  avg_hook_rate_pct: number;
  total_leads: number;
  total_post_engagements: number;
  total_impressions: number;
  total_reach: number;
  total_link_clicks: number;
  avg_cost_per_lead: Num;
  avg_cost_per_engagement: Num;
  avg_cpc: Num;
  avg_cpm: number;
  avg_ctr: number;

  prev_spend: Num;
  prev_purchases: number | null;
  prev_avg_cpa: Num;
  prev_avg_roas: Num;

  variants: VariantReport[];

  best_variant: VariantReport | null;
  best_variant_funnel: ReportFunnelStage[];
  best_variant_diagnostics: Diagnostic[];
  best_variant_projection: string | null;

  // Objective-aware display lists (pre-built server-side).
  headline_metrics: HeadlineMetric[];
  best_variant_summary: SummaryNumber[];
  best_variant_diagnostic_tiles: DiagnosticTile[];
  variant_table_columns: VariantTableColumn[];

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
  /**
   * Creative format (same taxonomy as ``VariantReport.media_type``).
   * The weekly variant table uses this to em-dash hook/hold columns
   * for image-only variants.
   */
  media_type: string;

  // Objective-aware fields.
  leads: number;
  post_engagements: number;
  cost_per_lead: Num;
  cost_per_engagement: Num;
  cpc: Num;
  cpm: Num;
  frequency: Num;
  hook_rate_pct: number;
  hold_rate_pct: number;
  ctr_pct: number;
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
  /** Canonical ODAX objective. */
  objective: string;

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
  avg_cpc: Num;
  avg_frequency: Num;
  avg_roas: Num;
  avg_cost_per_purchase: Num;
  total_leads: number;
  total_post_engagements: number;
  avg_cost_per_lead: Num;
  avg_cost_per_engagement: Num;
  lpv_rate_pct: number;

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

  // Objective-aware display lists.
  metric_rows: WeeklyMetricRow[];
  best_variant_summary: SummaryNumber[];
  best_variant_diagnostic_tiles: DiagnosticTile[];
  variant_table_columns: VariantTableColumn[];
}
