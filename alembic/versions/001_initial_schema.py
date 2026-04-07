"""Initial schema: all tables, indexes, views, and functions.

Revision ID: 001_initial
Revises: None
Create Date: 2026-04-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "timescaledb"')

    # ------------------------------------------------------------------
    # Enum types
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE variant_status AS ENUM (
            'draft', 'pending', 'active', 'paused', 'winner', 'retired'
        )
    """)
    op.execute("""
        CREATE TYPE cycle_phase AS ENUM (
            'monitor', 'analyze', 'generate', 'deploy', 'report', 'complete'
        )
    """)
    op.execute("""
        CREATE TYPE platform_type AS ENUM (
            'meta', 'google_ads', 'tiktok', 'linkedin'
        )
    """)
    op.execute("""
        CREATE TYPE action_type AS ENUM (
            'launch', 'pause', 'increase_budget', 'decrease_budget',
            'retire', 'promote_winner'
        )
    """)

    # ------------------------------------------------------------------
    # 1. gene_pool
    # ------------------------------------------------------------------
    op.create_table(
        "gene_pool",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("slot_name", sa.Text(), nullable=False),
        sa.Column("slot_value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slot_name", "slot_value", name="uq_gene_pool_slot_value"),
    )
    op.create_index(
        "idx_gene_pool_slot",
        "gene_pool",
        ["slot_name"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # ------------------------------------------------------------------
    # 2. campaigns
    # ------------------------------------------------------------------
    op.create_table(
        "campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("platform", sa.Enum("meta", "google_ads", "tiktok", "linkedin", name="platform_type", create_type=False), nullable=False),
        sa.Column("platform_campaign_id", sa.Text(), nullable=True),
        sa.Column("daily_budget", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_concurrent_variants", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("min_impressions_for_significance", sa.Integer(), nullable=False, server_default=sa.text("1000")),
        sa.Column("confidence_threshold", sa.Numeric(4, 3), nullable=False, server_default=sa.text("0.950")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ------------------------------------------------------------------
    # 3. variants
    # ------------------------------------------------------------------
    op.create_table(
        "variants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("variant_code", sa.Text(), nullable=False),
        sa.Column("genome", JSONB(), nullable=False),
        sa.Column("status", sa.Enum("draft", "pending", "active", "paused", "winner", "retired", name="variant_status", create_type=False), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("generation", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("parent_ids", sa.ARRAY(UUID(as_uuid=True)), server_default=sa.text("'{}'::uuid[]")),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("campaign_id", "variant_code", name="uq_variant_campaign_code"),
    )
    op.create_index("idx_variants_campaign", "variants", ["campaign_id", "status"])
    op.execute("CREATE INDEX idx_variants_genome ON variants USING gin (genome)")
    op.create_index(
        "idx_variants_status",
        "variants",
        ["status"],
        postgresql_where=sa.text("status = 'active'"),
    )

    # ------------------------------------------------------------------
    # 4. deployments
    # ------------------------------------------------------------------
    op.create_table(
        "deployments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("platform", sa.Enum("meta", "google_ads", "tiktok", "linkedin", name="platform_type", create_type=False), nullable=False),
        sa.Column("platform_ad_id", sa.Text(), nullable=False),
        sa.Column("platform_adset_id", sa.Text(), nullable=True),
        sa.Column("daily_budget", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("platform", "platform_ad_id", name="uq_deployment_platform_ad"),
    )
    op.create_index("idx_deployments_variant", "deployments", ["variant_id"])
    op.create_index(
        "idx_deployments_active",
        "deployments",
        ["is_active"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # ------------------------------------------------------------------
    # 5. metrics (TimescaleDB hypertable)
    # ------------------------------------------------------------------
    op.create_table(
        "metrics",
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("deployment_id", UUID(as_uuid=True), sa.ForeignKey("deployments.id"), nullable=False),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("clicks", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("conversions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("spend", sa.Numeric(10, 2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "ctr",
            sa.Numeric(8, 5),
            sa.Computed("CASE WHEN impressions > 0 THEN clicks::NUMERIC / impressions ELSE 0 END"),
        ),
        sa.Column(
            "cpc",
            sa.Numeric(10, 4),
            sa.Computed("CASE WHEN clicks > 0 THEN spend / clicks ELSE 0 END"),
        ),
        sa.Column(
            "cpa",
            sa.Numeric(10, 4),
            sa.Computed("CASE WHEN conversions > 0 THEN spend / conversions ELSE 0 END"),
        ),
    )

    # Composite primary key for the hypertable
    op.execute("ALTER TABLE metrics ADD PRIMARY KEY (recorded_at, variant_id)")

    # Convert to TimescaleDB hypertable (raw SQL required)
    op.execute("SELECT create_hypertable('metrics', 'recorded_at')")

    op.execute("CREATE INDEX idx_metrics_variant ON metrics (variant_id, recorded_at DESC)")
    op.execute("CREATE INDEX idx_metrics_deployment ON metrics (deployment_id, recorded_at DESC)")

    # ------------------------------------------------------------------
    # 6. metrics_daily continuous aggregate
    # ------------------------------------------------------------------
    op.execute("""
        CREATE MATERIALIZED VIEW metrics_daily
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 day', recorded_at) AS day,
            variant_id,
            MAX(impressions) AS impressions,
            MAX(clicks)      AS clicks,
            MAX(conversions) AS conversions,
            MAX(spend)       AS spend
        FROM metrics
        GROUP BY time_bucket('1 day', recorded_at), variant_id
        WITH NO DATA
    """)
    op.execute("""
        SELECT add_continuous_aggregate_policy('metrics_daily',
            start_offset    => INTERVAL '3 days',
            end_offset      => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour'
        )
    """)

    # ------------------------------------------------------------------
    # 7. element_performance
    # ------------------------------------------------------------------
    op.create_table(
        "element_performance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("slot_name", sa.Text(), nullable=False),
        sa.Column("slot_value", sa.Text(), nullable=False),
        sa.Column("variants_tested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("avg_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("avg_cpa", sa.Numeric(10, 4), nullable=True),
        sa.Column("best_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("worst_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("total_impressions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_conversions", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("campaign_id", "slot_name", "slot_value", name="uq_element_perf_campaign_slot"),
    )
    op.create_index("idx_element_perf_slot", "element_performance", ["campaign_id", "slot_name"])

    # ------------------------------------------------------------------
    # 8. element_interactions
    # ------------------------------------------------------------------
    op.create_table(
        "element_interactions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("slot_a_name", sa.Text(), nullable=False),
        sa.Column("slot_a_value", sa.Text(), nullable=False),
        sa.Column("slot_b_name", sa.Text(), nullable=False),
        sa.Column("slot_b_value", sa.Text(), nullable=False),
        sa.Column("variants_tested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("combined_avg_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("solo_a_avg_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("solo_b_avg_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("interaction_lift", sa.Numeric(8, 4), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint(
            "campaign_id", "slot_a_name", "slot_a_value", "slot_b_name", "slot_b_value",
            name="uq_interaction_pair",
        ),
        sa.CheckConstraint(
            "slot_a_name < slot_b_name OR (slot_a_name = slot_b_name AND slot_a_value < slot_b_value)",
            name="ck_canonical_ordering",
        ),
    )
    op.create_index("idx_interactions_campaign", "element_interactions", ["campaign_id"])
    op.execute(
        "CREATE INDEX idx_interactions_lift ON element_interactions "
        "(interaction_lift DESC NULLS LAST)"
    )

    # ------------------------------------------------------------------
    # 9. test_cycles
    # ------------------------------------------------------------------
    op.create_table(
        "test_cycles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Enum("monitor", "analyze", "generate", "deploy", "report", "complete", name="cycle_phase", create_type=False), nullable=False, server_default=sa.text("'monitor'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("variants_active", sa.Integer(), nullable=True),
        sa.Column("variants_launched", sa.Integer(), server_default=sa.text("0")),
        sa.Column("variants_paused", sa.Integer(), server_default=sa.text("0")),
        sa.Column("variants_promoted", sa.Integer(), server_default=sa.text("0")),
        sa.Column("total_spend", sa.Numeric(10, 2), nullable=True),
        sa.Column("avg_ctr", sa.Numeric(8, 5), nullable=True),
        sa.Column("avg_cpa", sa.Numeric(10, 4), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.UniqueConstraint("campaign_id", "cycle_number", name="uq_cycle_campaign_number"),
    )
    op.execute(
        "CREATE INDEX idx_cycles_campaign ON test_cycles (campaign_id, cycle_number DESC)"
    )

    # ------------------------------------------------------------------
    # 10. cycle_actions
    # ------------------------------------------------------------------
    op.create_table(
        "cycle_actions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("cycle_id", UUID(as_uuid=True), sa.ForeignKey("test_cycles.id"), nullable=False),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("variants.id"), nullable=True),
        sa.Column("action", sa.Enum("launch", "pause", "increase_budget", "decrease_budget", "retire", "promote_winner", name="action_type", create_type=False), nullable=False),
        sa.Column("details", JSONB(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_actions_cycle", "cycle_actions", ["cycle_id"])
    op.create_index("idx_actions_variant", "cycle_actions", ["variant_id"])

    # ------------------------------------------------------------------
    # 11. approval_queue
    # ------------------------------------------------------------------
    op.create_table(
        "approval_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("variant_id", UUID(as_uuid=True), sa.ForeignKey("variants.id"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("genome_snapshot", JSONB(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewer", sa.Text(), nullable=True),
        sa.Column("approved", sa.Boolean(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_approval_pending",
        "approval_queue",
        ["campaign_id"],
        postgresql_where=sa.text("approved IS NULL"),
    )

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------
    op.execute("""
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
            SELECT impressions, clicks, conversions, spend
            FROM metrics
            WHERE variant_id = v.id
            ORDER BY recorded_at DESC
            LIMIT 1
        ) m ON TRUE
        WHERE v.status IN ('active', 'winner')
        ORDER BY ctr_pct DESC NULLS LAST
    """)

    op.execute("""
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
        ORDER BY ep.slot_name, rank_in_slot
    """)

    op.execute("""
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
        LIMIT 20
    """)

    # ------------------------------------------------------------------
    # Helper functions
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION next_variant_code(p_campaign_id UUID)
        RETURNS TEXT AS $$
            SELECT 'V' || (COALESCE(
                MAX(NULLIF(regexp_replace(variant_code, '[^0-9]', '', 'g'), '')::INT),
                0
            ) + 1)::TEXT
            FROM variants
            WHERE campaign_id = p_campaign_id;
        $$ LANGUAGE SQL
    """)

    op.execute("""
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
        $$ LANGUAGE SQL
    """)

    op.execute("""
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
        $$ LANGUAGE SQL
    """)

    # ------------------------------------------------------------------
    # Seed data — starter gene pool
    # ------------------------------------------------------------------
    op.execute("""
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
            ('audience', 'broad',                                   'Broad targeting, no filters')
    """)


def downgrade() -> None:
    # ------------------------------------------------------------------
    # Drop in reverse order of creation
    # ------------------------------------------------------------------

    # Functions
    op.execute("DROP FUNCTION IF EXISTS remaining_budget(UUID)")
    op.execute("DROP FUNCTION IF EXISTS genome_exists(UUID, JSONB)")
    op.execute("DROP FUNCTION IF EXISTS next_variant_code(UUID)")

    # Views
    op.execute("DROP VIEW IF EXISTS top_interactions")
    op.execute("DROP VIEW IF EXISTS element_rankings")
    op.execute("DROP VIEW IF EXISTS variant_leaderboard")

    # Continuous aggregate (must drop policy first)
    op.execute("""
        SELECT remove_continuous_aggregate_policy('metrics_daily', if_exists => true)
    """)
    op.execute("DROP MATERIALIZED VIEW IF EXISTS metrics_daily")

    # Tables (reverse dependency order)
    op.drop_table("approval_queue")
    op.drop_table("cycle_actions")
    op.drop_table("test_cycles")
    op.drop_table("element_interactions")
    op.drop_table("element_performance")
    op.drop_table("metrics")
    op.drop_table("deployments")
    op.drop_table("variants")
    op.drop_table("campaigns")
    op.drop_table("gene_pool")

    # Enum types
    op.execute("DROP TYPE IF EXISTS action_type")
    op.execute("DROP TYPE IF EXISTS platform_type")
    op.execute("DROP TYPE IF EXISTS cycle_phase")
    op.execute("DROP TYPE IF EXISTS variant_status")
