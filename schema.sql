-- =============================================================
-- Ad creative testing agent system — database schema
-- PostgreSQL 16 + TimescaleDB
-- =============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "timescaledb";

-- Custom enum types
CREATE TYPE variant_status AS ENUM (
    'draft',        -- created by generator, not yet deployed
    'pending',      -- awaiting human approval (if gate enabled)
    'active',       -- live on platform, receiving traffic
    'paused',       -- temporarily stopped (low performance / budget)
    'winner',       -- statistically significant outperformer
    'retired'       -- test complete, archived
);

CREATE TYPE cycle_phase AS ENUM (
    'monitor',      -- pulling metrics from platforms
    'analyze',      -- running statistical tests
    'generate',     -- creating new variant genomes
    'deploy',       -- pushing variants to ad platforms
    'report',       -- sending daily/weekly summaries
    'complete'
);

CREATE TYPE platform_type AS ENUM (
    'meta',
    'google_ads',
    'tiktok',
    'linkedin'
);

CREATE TYPE action_type AS ENUM (
    'launch',           -- new variant deployed
    'pause',            -- variant paused for poor performance
    'increase_budget',  -- winner scaled up
    'decrease_budget',  -- underperformer scaled down
    'retire',           -- test concluded
    'promote_winner'    -- variant declared winner
);


-- =============================================================
-- 1. GENE POOL
-- The library of approved creative elements per slot.
-- Each row is one option for one slot. The generator agent
-- can only select from values that exist here.
-- =============================================================

CREATE TABLE gene_pool (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slot_name       TEXT NOT NULL,           -- e.g. 'headline', 'cta_color', 'audience'
    slot_value      TEXT NOT NULL,           -- the actual content or identifier
    description     TEXT,                    -- human-readable note for reports
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at      TIMESTAMPTZ,

    UNIQUE (slot_name, slot_value)
);

CREATE INDEX idx_gene_pool_slot ON gene_pool (slot_name) WHERE is_active = TRUE;

COMMENT ON TABLE gene_pool IS
    'Pre-approved creative elements. The generator agent draws from this pool. '
    'New entries require human approval. Retiring an entry prevents future use '
    'but does not affect active variants using it.';


-- =============================================================
-- 2. CAMPAIGNS
-- Top-level container. One campaign = one product/goal with
-- its own budget, audience, and test loop.
-- =============================================================

CREATE TABLE campaigns (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    platform        platform_type NOT NULL,
    platform_campaign_id TEXT,              -- external ID on the ad platform
    daily_budget    NUMERIC(10,2) NOT NULL,
    max_concurrent_variants INT NOT NULL DEFAULT 10,
    min_impressions_for_significance INT NOT NULL DEFAULT 1000,
    confidence_threshold NUMERIC(4,3) NOT NULL DEFAULT 0.950,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =============================================================
-- 3. VARIANTS
-- Each row is a single creative variant with its full genome.
-- The genome is stored as JSONB for flexible slot schemas.
-- =============================================================

CREATE TABLE variants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    variant_code    TEXT NOT NULL,           -- human-readable label, e.g. 'V7'
    genome          JSONB NOT NULL,          -- the creative genome
    status          variant_status NOT NULL DEFAULT 'draft',
    generation      INT NOT NULL DEFAULT 1, -- which optimization cycle created this
    parent_ids      UUID[] DEFAULT '{}',    -- variants this was bred from
    hypothesis      TEXT,                   -- what this variant is testing
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deployed_at     TIMESTAMPTZ,
    paused_at       TIMESTAMPTZ,
    retired_at      TIMESTAMPTZ,

    UNIQUE (campaign_id, variant_code)
);

CREATE INDEX idx_variants_campaign ON variants (campaign_id, status);
CREATE INDEX idx_variants_genome ON variants USING gin (genome);
CREATE INDEX idx_variants_status ON variants (status) WHERE status = 'active';

COMMENT ON COLUMN variants.genome IS
    'JSONB object where each key is a slot name (matching gene_pool.slot_name) '
    'and each value is a slot value (matching gene_pool.slot_value). Example: '
    '{"headline": "Limited time offer", "cta_color": "green", "audience": "retargeting_30d"}';

COMMENT ON COLUMN variants.hypothesis IS
    'What this variant is testing, generated by the variation generator agent. '
    'e.g. "Testing urgency headline with green CTA (proven winner) on cold audience (untested)"';


-- =============================================================
-- 4. DEPLOYMENTS
-- Maps variants to their platform-specific ad objects.
-- A variant may have multiple deployments (one per platform).
-- =============================================================

CREATE TABLE deployments (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    variant_id      UUID NOT NULL REFERENCES variants(id),
    platform        platform_type NOT NULL,
    platform_ad_id  TEXT NOT NULL,          -- the ad ID on the platform
    platform_adset_id TEXT,                 -- ad set / ad group ID
    daily_budget    NUMERIC(10,2) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (platform, platform_ad_id)
);

CREATE INDEX idx_deployments_variant ON deployments (variant_id);
CREATE INDEX idx_deployments_active ON deployments (is_active) WHERE is_active = TRUE;


-- =============================================================
-- 5. METRICS TIMESERIES
-- Raw performance data polled from ad platforms every 6 hours.
-- Converted to a TimescaleDB hypertable for efficient
-- time-bucketing queries.
-- =============================================================

CREATE TABLE metrics (
    recorded_at     TIMESTAMPTZ NOT NULL,
    variant_id      UUID NOT NULL REFERENCES variants(id),
    deployment_id   UUID NOT NULL REFERENCES deployments(id),
    impressions     INT NOT NULL DEFAULT 0,
    clicks          INT NOT NULL DEFAULT 0,
    conversions     INT NOT NULL DEFAULT 0,
    spend           NUMERIC(10,2) NOT NULL DEFAULT 0,
    ctr             NUMERIC(8,5) GENERATED ALWAYS AS (
                        CASE WHEN impressions > 0
                             THEN clicks::NUMERIC / impressions
                             ELSE 0 END
                    ) STORED,
    cpc             NUMERIC(10,4) GENERATED ALWAYS AS (
                        CASE WHEN clicks > 0
                             THEN spend / clicks
                             ELSE 0 END
                    ) STORED,
    cpa             NUMERIC(10,4) GENERATED ALWAYS AS (
                        CASE WHEN conversions > 0
                             THEN spend / conversions
                             ELSE 0 END
                    ) STORED
);

SELECT create_hypertable('metrics', 'recorded_at');

CREATE INDEX idx_metrics_variant ON metrics (variant_id, recorded_at DESC);
CREATE INDEX idx_metrics_deployment ON metrics (deployment_id, recorded_at DESC);

COMMENT ON TABLE metrics IS
    'Raw metrics from ad platforms, polled every 6 hours. Each row is a '
    'cumulative snapshot at that point in time. Use time_bucket() for '
    'daily/weekly aggregations. Generated columns compute derived rates.';


-- =============================================================
-- 6. METRICS — DAILY ROLLUP (continuous aggregate)
-- Precomputed daily summaries for fast dashboard queries
-- and analyst agent consumption.
-- =============================================================

CREATE MATERIALIZED VIEW metrics_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', recorded_at)   AS day,
    variant_id,
    MAX(impressions)                     AS impressions,
    MAX(clicks)                          AS clicks,
    MAX(conversions)                     AS conversions,
    MAX(spend)                           AS spend
WITH NO DATA;

SELECT add_continuous_aggregate_policy('metrics_daily',
    start_offset    => INTERVAL '3 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

COMMENT ON MATERIALIZED VIEW metrics_daily IS
    'Continuous aggregate rolling up metrics to daily granularity. '
    'Uses MAX because platform metrics are cumulative snapshots.';


-- =============================================================
-- 7. ELEMENT PERFORMANCE
-- Aggregated performance for each gene pool element across
-- all variants that used it. This is the knowledge base that
-- compounds over time.
-- =============================================================

CREATE TABLE element_performance (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    slot_name       TEXT NOT NULL,
    slot_value      TEXT NOT NULL,
    variants_tested INT NOT NULL DEFAULT 0,
    avg_ctr         NUMERIC(8,5),
    avg_cpa         NUMERIC(10,4),
    best_ctr        NUMERIC(8,5),
    worst_ctr       NUMERIC(8,5),
    total_impressions BIGINT NOT NULL DEFAULT 0,
    total_conversions BIGINT NOT NULL DEFAULT 0,
    confidence      NUMERIC(5,2),           -- statistical confidence %
    last_tested_at  TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (campaign_id, slot_name, slot_value)
);

CREATE INDEX idx_element_perf_slot ON element_performance (campaign_id, slot_name);

COMMENT ON TABLE element_performance IS
    'Aggregated performance for individual creative elements. Updated '
    'by the analyst agent after each cycle. This table answers questions '
    'like "how do urgency headlines perform across all variants?"';


-- =============================================================
-- 8. ELEMENT INTERACTIONS
-- Tracks how pairs of elements perform together vs. alone.
-- This captures the combinatorial effects that single-element
-- analysis misses.
-- =============================================================

CREATE TABLE element_interactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    slot_a_name     TEXT NOT NULL,
    slot_a_value    TEXT NOT NULL,
    slot_b_name     TEXT NOT NULL,
    slot_b_value    TEXT NOT NULL,
    variants_tested INT NOT NULL DEFAULT 0,
    combined_avg_ctr    NUMERIC(8,5),
    solo_a_avg_ctr      NUMERIC(8,5),       -- element A's avg without B
    solo_b_avg_ctr      NUMERIC(8,5),       -- element B's avg without A
    interaction_lift    NUMERIC(8,4),        -- % lift of combined vs. best solo
    confidence          NUMERIC(5,2),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (campaign_id, slot_a_name, slot_a_value, slot_b_name, slot_b_value),

    -- Enforce canonical ordering so (A,B) and (B,A) don't both exist
    CHECK (slot_a_name < slot_b_name OR
           (slot_a_name = slot_b_name AND slot_a_value < slot_b_value))
);

CREATE INDEX idx_interactions_campaign ON element_interactions (campaign_id);
CREATE INDEX idx_interactions_lift ON element_interactions (interaction_lift DESC NULLS LAST);

COMMENT ON TABLE element_interactions IS
    'Pairwise interaction effects between creative elements. Positive '
    'interaction_lift means the combo is better than either element alone. '
    'The CHECK constraint enforces canonical pair ordering to prevent dupes.';


-- =============================================================
-- 9. TEST CYCLES
-- One row per orchestrator execution. Tracks what happened
-- during each automated optimization cycle.
-- =============================================================

CREATE TABLE test_cycles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    cycle_number    INT NOT NULL,
    phase           cycle_phase NOT NULL DEFAULT 'monitor',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    variants_active INT,
    variants_launched INT DEFAULT 0,
    variants_paused INT DEFAULT 0,
    variants_promoted INT DEFAULT 0,
    total_spend     NUMERIC(10,2),
    avg_ctr         NUMERIC(8,5),
    avg_cpa         NUMERIC(10,4),
    summary_text    TEXT,                   -- LLM-generated natural language summary
    error_log       TEXT,

    UNIQUE (campaign_id, cycle_number)
);

CREATE INDEX idx_cycles_campaign ON test_cycles (campaign_id, cycle_number DESC);


-- =============================================================
-- 10. CYCLE ACTIONS
-- Granular log of every action the orchestrator took during
-- a cycle. Provides full audit trail and debugging.
-- =============================================================

CREATE TABLE cycle_actions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_id        UUID NOT NULL REFERENCES test_cycles(id),
    variant_id      UUID REFERENCES variants(id),
    action          action_type NOT NULL,
    details         JSONB,                  -- action-specific payload
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_actions_cycle ON cycle_actions (cycle_id);
CREATE INDEX idx_actions_variant ON cycle_actions (variant_id);

COMMENT ON TABLE cycle_actions IS
    'Audit log for orchestrator decisions. Every launch, pause, budget '
    'change, and promotion is recorded with its full context in the '
    'details JSONB column.';


-- =============================================================
-- 11. APPROVAL QUEUE (optional human-in-the-loop gate)
-- Variants land here before deployment if the approval gate
-- is enabled on the campaign.
-- =============================================================

CREATE TABLE approval_queue (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    variant_id      UUID NOT NULL REFERENCES variants(id),
    campaign_id     UUID NOT NULL REFERENCES campaigns(id),
    genome_snapshot JSONB NOT NULL,
    hypothesis      TEXT,
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at     TIMESTAMPTZ,
    reviewer        TEXT,                   -- Slack user ID or email
    approved        BOOLEAN,
    rejection_reason TEXT
);

CREATE INDEX idx_approval_pending ON approval_queue (campaign_id)
    WHERE approved IS NULL;


-- =============================================================
-- HELPER VIEWS
-- =============================================================

-- Active variant leaderboard with latest metrics
CREATE VIEW variant_leaderboard AS
SELECT
    v.id,
    v.variant_code,
    v.genome,
    v.status,
    v.generation,
    v.hypothesis,
    v.deployed_at,
    m.impressions,
    m.clicks,
    m.conversions,
    m.spend,
    CASE WHEN m.impressions > 0
         THEN ROUND(m.clicks::NUMERIC / m.impressions * 100, 2)
         ELSE 0 END                     AS ctr_pct,
    CASE WHEN m.conversions > 0
         THEN ROUND(m.spend / m.conversions, 2)
         ELSE NULL END                  AS cpa,
    c.min_impressions_for_significance,
    CASE WHEN m.impressions >= c.min_impressions_for_significance
         THEN TRUE ELSE FALSE END       AS has_sufficient_data
FROM variants v
JOIN campaigns c ON c.id = v.campaign_id
LEFT JOIN LATERAL (
    SELECT
        impressions, clicks, conversions, spend
    FROM metrics
    WHERE variant_id = v.id
    ORDER BY recorded_at DESC
    LIMIT 1
) m ON TRUE
WHERE v.status IN ('active', 'winner')
ORDER BY ctr_pct DESC NULLS LAST;

COMMENT ON VIEW variant_leaderboard IS
    'Quick snapshot of all active/winning variants ranked by CTR. '
    'Used by the daily summary and dashboard.';


-- Element performance ranked by slot
CREATE VIEW element_rankings AS
SELECT
    ep.slot_name,
    ep.slot_value,
    ep.avg_ctr,
    ep.avg_cpa,
    ep.variants_tested,
    ep.confidence,
    ep.total_impressions,
    RANK() OVER (
        PARTITION BY ep.slot_name
        ORDER BY ep.avg_ctr DESC NULLS LAST
    ) AS rank_in_slot
FROM element_performance ep
WHERE ep.variants_tested >= 2
ORDER BY ep.slot_name, rank_in_slot;

COMMENT ON VIEW element_rankings IS
    'Elements ranked within their slot by average CTR. Only includes '
    'elements tested in 2+ variants. Fed to the generator agent to '
    'inform the next round of combinations.';


-- Top positive and negative interactions
CREATE VIEW top_interactions AS
SELECT
    ei.slot_a_name || ': ' || ei.slot_a_value AS element_a,
    ei.slot_b_name || ': ' || ei.slot_b_value AS element_b,
    ROUND(ei.interaction_lift * 100, 1) AS lift_pct,
    ei.combined_avg_ctr,
    ei.variants_tested,
    ei.confidence
FROM element_interactions ei
WHERE ei.confidence >= 85
ORDER BY ABS(ei.interaction_lift) DESC
LIMIT 20;


-- =============================================================
-- HELPER FUNCTIONS
-- =============================================================

-- Generate the next variant code for a campaign (V1, V2, ...)
CREATE OR REPLACE FUNCTION next_variant_code(p_campaign_id UUID)
RETURNS TEXT AS $$
    SELECT 'V' || (COALESCE(
        MAX(NULLIF(regexp_replace(variant_code, '[^0-9]', '', 'g'), '')::INT),
        0
    ) + 1)::TEXT
    FROM variants
    WHERE campaign_id = p_campaign_id;
$$ LANGUAGE SQL;


-- Check if a genome already exists in a campaign (dedup)
CREATE OR REPLACE FUNCTION genome_exists(
    p_campaign_id UUID,
    p_genome JSONB
) RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM variants
        WHERE campaign_id = p_campaign_id
          AND genome @> p_genome
          AND genome <@ p_genome
          AND status NOT IN ('retired')
    );
$$ LANGUAGE SQL;


-- Calculate remaining budget capacity for a campaign
CREATE OR REPLACE FUNCTION remaining_budget(p_campaign_id UUID)
RETURNS NUMERIC AS $$
    SELECT c.daily_budget - COALESCE(SUM(d.daily_budget), 0)
    FROM campaigns c
    LEFT JOIN deployments d ON d.variant_id IN (
        SELECT id FROM variants
        WHERE campaign_id = c.id AND status = 'active'
    ) AND d.is_active = TRUE
    WHERE c.id = p_campaign_id
    GROUP BY c.daily_budget;
$$ LANGUAGE SQL;


-- =============================================================
-- SEED DATA — starter gene pool
-- =============================================================

INSERT INTO gene_pool (slot_name, slot_value, description) VALUES
    -- Headlines
    ('headline', 'Limited time: 40% off today only',       'Urgency + discount'),
    ('headline', 'Join 12,000+ happy customers',            'Social proof + count'),
    ('headline', 'What are you waiting for?',               'Question style'),
    ('headline', 'The smarter choice for your team',        'Benefit focused'),
    ('headline', 'Stop wasting money on [competitor]',      'Competitive callout'),
    ('headline', 'See why teams are switching',             'Curiosity + social proof'),
    ('headline', 'Your team deserves better tools',         'Aspirational'),
    ('headline', 'Try it free — no credit card needed',     'Low friction offer'),

    -- Subheadlines
    ('subhead', 'Join 12,000+ happy customers',             'Social proof count'),
    ('subhead', 'As seen in Forbes and TechCrunch',         'Press mentions'),
    ('subhead', 'Rated 4.9/5 by verified users',            'Rating proof'),
    ('subhead', 'Setup takes less than 5 minutes',          'Ease of use'),
    ('subhead', 'Free 14-day trial, cancel anytime',        'Risk reversal'),

    -- CTA text
    ('cta_text', 'Get started free',                        'Low commitment'),
    ('cta_text', 'Claim my discount',                       'Ownership language'),
    ('cta_text', 'Start my free trial',                     'Trial focused'),
    ('cta_text', 'See it in action',                        'Demo oriented'),
    ('cta_text', 'Learn more',                              'Soft CTA'),

    -- CTA color
    ('cta_color', 'green',                                  'High contrast, action'),
    ('cta_color', 'blue',                                   'Trust, professional'),
    ('cta_color', 'orange',                                 'Energetic, attention'),
    ('cta_color', 'black',                                  'Premium, minimal'),

    -- Hero image style
    ('hero_style', 'lifestyle_photo',                       'People using product'),
    ('hero_style', 'product_screenshot',                    'UI/product shot'),
    ('hero_style', 'illustration',                          'Custom illustration'),
    ('hero_style', 'testimonial_card',                      'Quote with headshot'),

    -- Social proof type
    ('social_proof', 'customer_count',                      '"12,000+ customers"'),
    ('social_proof', 'testimonial',                         'Named customer quote'),
    ('social_proof', 'press_logos',                          'Media outlet logos'),
    ('social_proof', 'rating',                              'Star rating badge'),
    ('social_proof', 'none',                                'No social proof'),

    -- Urgency element
    ('urgency', 'time_limited',                             '"Ends tonight" style'),
    ('urgency', 'stock_limited',                            '"Only X spots left"'),
    ('urgency', 'seasonal',                                 'Tied to event/season'),
    ('urgency', 'none',                                     'No urgency element'),

    -- Audience segment
    ('audience', 'retargeting_30d',                         'Site visitors, last 30 days'),
    ('audience', 'retargeting_7d',                          'Site visitors, last 7 days'),
    ('audience', 'lookalike_1pct',                          '1% lookalike of converters'),
    ('audience', 'lookalike_5pct',                          '5% lookalike of converters'),
    ('audience', 'interest_based',                          'Interest/behavior targeting'),
    ('audience', 'broad',                                   'Broad targeting, no filters');
