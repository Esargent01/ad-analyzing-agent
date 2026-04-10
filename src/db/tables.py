"""SQLAlchemy 2.0 ORM models for all database tables."""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class VariantStatus(str, enum.Enum):
    draft = "draft"
    pending = "pending"
    active = "active"
    paused = "paused"
    winner = "winner"
    retired = "retired"


class CyclePhase(str, enum.Enum):
    monitor = "monitor"
    analyze = "analyze"
    generate = "generate"
    deploy = "deploy"
    report = "report"
    complete = "complete"


class PlatformType(str, enum.Enum):
    meta = "meta"
    google_ads = "google_ads"
    tiktok = "tiktok"
    linkedin = "linkedin"


class ActionType(str, enum.Enum):
    launch = "launch"
    pause = "pause"
    increase_budget = "increase_budget"
    decrease_budget = "decrease_budget"
    retire = "retire"
    promote_winner = "promote_winner"
    queue_for_approval = "queue_for_approval"


class ApprovalActionType(str, enum.Enum):
    """What kind of change an approval_queue row represents.

    Introduced in Phase H — before then every row was implicitly a
    ``new_variant`` proposal. Kept as a separate enum from
    ``ActionType`` (which is the audit-log vocabulary on
    ``cycle_actions``) so the two can evolve independently.
    """

    new_variant = "new_variant"
    pause_variant = "pause_variant"
    scale_budget = "scale_budget"
    promote_winner = "promote_winner"


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class GenePoolEntry(Base):
    __tablename__ = "gene_pool"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    slot_name: Mapped[str] = mapped_column(Text, nullable=False)
    slot_value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB)
    source: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("slot_name", "slot_value", name="uq_gene_pool_slot_value"),
        Index("idx_gene_pool_slot", "slot_name", postgresql_where="is_active = TRUE"),
    )

    def __repr__(self) -> str:
        return f"<GenePoolEntry slot={self.slot_name!r} value={self.slot_value!r}>"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[PlatformType] = mapped_column(
        Enum(PlatformType, name="platform_type", create_type=False), nullable=False
    )
    platform_campaign_id: Mapped[str | None] = mapped_column(Text)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_concurrent_variants: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    min_impressions_for_significance: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1000"
    )
    confidence_threshold: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, server_default="0.950"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Nullable until Phase F backfills legacy campaigns. Adapter
    # factory treats NULL as "fall back to global token" during the
    # transition; Phase F drops that fallback and makes the column
    # NOT NULL.
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # Phase G — per-campaign Meta tenancy. ``meta_ad_account_id`` and
    # ``meta_page_id`` are enforced NOT NULL for ``platform = 'meta'``
    # rows via a partial CHECK constraint (see migration 009), but
    # are nullable on the Python side so future non-Meta platforms
    # aren't dragged in. ``landing_page_url`` is genuinely optional
    # — the import flow treats it as a per-product free-text field.
    meta_ad_account_id: Mapped[str | None] = mapped_column(Text)
    meta_page_id: Mapped[str | None] = mapped_column(Text)
    landing_page_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Relationships
    variants: Mapped[list[Variant]] = relationship(back_populates="campaign", lazy="selectin")
    test_cycles: Mapped[list[TestCycle]] = relationship(back_populates="campaign", lazy="selectin")
    element_performances: Mapped[list[ElementPerformance]] = relationship(
        back_populates="campaign", lazy="selectin"
    )
    element_interactions: Mapped[list[ElementInteraction]] = relationship(
        back_populates="campaign", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Campaign name={self.name!r} platform={self.platform.value}>"


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    variant_code: Mapped[str] = mapped_column(Text, nullable=False)
    genome: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[VariantStatus] = mapped_column(
        Enum(VariantStatus, name="variant_status", create_type=False),
        nullable=False,
        server_default="draft",
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    parent_ids: Mapped[list[UUID] | None] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), server_default="{}"
    )
    hypothesis: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    campaign: Mapped[Campaign] = relationship(back_populates="variants")
    deployments: Mapped[list[Deployment]] = relationship(back_populates="variant", lazy="selectin")
    metrics: Mapped[list[Metric]] = relationship(back_populates="variant", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("campaign_id", "variant_code", name="uq_variant_campaign_code"),
        Index("idx_variants_campaign", "campaign_id", "status"),
        Index("idx_variants_status", "status", postgresql_where="status = 'active'"),
    )

    def __repr__(self) -> str:
        return f"<Variant code={self.variant_code!r} status={self.status.value}>"


class Deployment(Base):
    __tablename__ = "deployments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("variants.id"), nullable=False
    )
    platform: Mapped[PlatformType] = mapped_column(
        Enum(PlatformType, name="platform_type", create_type=False), nullable=False
    )
    platform_ad_id: Mapped[str] = mapped_column(Text, nullable=False)
    platform_adset_id: Mapped[str | None] = mapped_column(Text)
    daily_budget: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Relationships
    variant: Mapped[Variant] = relationship(back_populates="deployments")
    metrics: Mapped[list[Metric]] = relationship(back_populates="deployment", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("platform", "platform_ad_id", name="uq_deployment_platform_ad"),
        Index("idx_deployments_variant", "variant_id"),
        Index("idx_deployments_active", "is_active", postgresql_where="is_active = TRUE"),
    )

    def __repr__(self) -> str:
        return f"<Deployment platform={self.platform.value} ad_id={self.platform_ad_id!r}>"


class Metric(Base):
    __tablename__ = "metrics"

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, primary_key=True
    )
    variant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("variants.id"), nullable=False, primary_key=True
    )
    deployment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deployments.id"), nullable=False
    )
    impressions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    clicks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    conversions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    spend: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, server_default="0")

    # Generated columns (read-only, computed by the database).
    # NOTE: the live ``metrics`` hypertable does NOT have a ``cpa`` column —
    # the effective "cost per acquisition" metric is ``cost_per_purchase``.
    # Historically the ORM declared ``cpa`` here, which broke any query that
    # triggered a full ORM load of the row (e.g. ``selectin`` eager loading
    # from variants). Keep this model aligned with the real schema.
    ctr: Mapped[Decimal] = mapped_column(
        Numeric(8, 5),
        Computed("CASE WHEN impressions > 0 THEN clicks::NUMERIC / impressions ELSE 0 END"),
    )
    cpc: Mapped[Decimal] = mapped_column(
        Numeric(10, 4),
        Computed("CASE WHEN clicks > 0 THEN spend / clicks ELSE 0 END"),
    )

    # Relationships
    variant: Mapped[Variant] = relationship(back_populates="metrics")
    deployment: Mapped[Deployment] = relationship(back_populates="metrics")

    __table_args__ = (
        Index("idx_metrics_variant", "variant_id", recorded_at.desc()),
        Index("idx_metrics_deployment", "deployment_id", recorded_at.desc()),
    )

    def __repr__(self) -> str:
        return f"<Metric variant={self.variant_id} at={self.recorded_at}>"


class ElementPerformance(Base):
    __tablename__ = "element_performance"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    slot_name: Mapped[str] = mapped_column(Text, nullable=False)
    slot_value: Mapped[str] = mapped_column(Text, nullable=False)
    variants_tested: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    avg_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    avg_cpa: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    best_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    worst_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    total_impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    total_conversions: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Relationships
    campaign: Mapped[Campaign] = relationship(back_populates="element_performances")

    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "slot_name", "slot_value", name="uq_element_perf_campaign_slot"
        ),
        Index("idx_element_perf_slot", "campaign_id", "slot_name"),
    )

    def __repr__(self) -> str:
        return f"<ElementPerformance slot={self.slot_name!r} value={self.slot_value!r} ctr={self.avg_ctr}>"


class ElementInteraction(Base):
    __tablename__ = "element_interactions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    slot_a_name: Mapped[str] = mapped_column(Text, nullable=False)
    slot_a_value: Mapped[str] = mapped_column(Text, nullable=False)
    slot_b_name: Mapped[str] = mapped_column(Text, nullable=False)
    slot_b_value: Mapped[str] = mapped_column(Text, nullable=False)
    variants_tested: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    combined_avg_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    solo_a_avg_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    solo_b_avg_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    interaction_lift: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Relationships
    campaign: Mapped[Campaign] = relationship(back_populates="element_interactions")

    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "slot_a_name",
            "slot_a_value",
            "slot_b_name",
            "slot_b_value",
            name="uq_interaction_pair",
        ),
        CheckConstraint(
            "slot_a_name < slot_b_name OR (slot_a_name = slot_b_name AND slot_a_value < slot_b_value)",
            name="ck_canonical_ordering",
        ),
        Index("idx_interactions_campaign", "campaign_id"),
        Index("idx_interactions_lift", interaction_lift.desc().nulls_last()),
    )

    def __repr__(self) -> str:
        return (
            f"<ElementInteraction {self.slot_a_name}:{self.slot_a_value} "
            f"x {self.slot_b_name}:{self.slot_b_value} lift={self.interaction_lift}>"
        )


class TestCycle(Base):
    __tablename__ = "test_cycles"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[CyclePhase] = mapped_column(
        Enum(CyclePhase, name="cycle_phase", create_type=False),
        nullable=False,
        server_default="monitor",
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    variants_active: Mapped[int | None] = mapped_column(Integer)
    variants_launched: Mapped[int] = mapped_column(Integer, server_default="0")
    variants_paused: Mapped[int] = mapped_column(Integer, server_default="0")
    variants_promoted: Mapped[int] = mapped_column(Integer, server_default="0")
    total_spend: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    avg_ctr: Mapped[Decimal | None] = mapped_column(Numeric(8, 5))
    avg_cpa: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    summary_text: Mapped[str | None] = mapped_column(Text)
    error_log: Mapped[str | None] = mapped_column(Text)

    # Relationships
    campaign: Mapped[Campaign] = relationship(back_populates="test_cycles")
    actions: Mapped[list[CycleAction]] = relationship(back_populates="cycle", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("campaign_id", "cycle_number", name="uq_cycle_campaign_number"),
        Index("idx_cycles_campaign", "campaign_id", cycle_number.desc()),
    )

    def __repr__(self) -> str:
        return f"<TestCycle campaign={self.campaign_id} number={self.cycle_number} phase={self.phase.value}>"


class CycleAction(Base):
    __tablename__ = "cycle_actions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    cycle_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_cycles.id"), nullable=False
    )
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("variants.id")
    )
    action: Mapped[ActionType] = mapped_column(
        Enum(ActionType, name="action_type", create_type=False), nullable=False
    )
    details: Mapped[dict | None] = mapped_column(JSONB)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    # Relationships
    cycle: Mapped[TestCycle] = relationship(back_populates="actions")
    variant: Mapped[Variant | None] = relationship()

    __table_args__ = (
        Index("idx_actions_cycle", "cycle_id"),
        Index("idx_actions_variant", "variant_id"),
    )

    def __repr__(self) -> str:
        return f"<CycleAction action={self.action.value} variant={self.variant_id}>"


class User(Base):
    """A dashboard user authenticated via email magic link.

    Users self-provision: the first successful magic-link verify for an
    unknown email creates a user row. ``last_login_at`` is refreshed every
    time the user verifies a magic link.
    """

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("idx_users_email", "email"),
    )

    def __repr__(self) -> str:
        return f"<User email={self.email!r}>"


class UserCampaign(Base):
    """Join table controlling which campaigns a user can access."""

    __tablename__ = "user_campaigns"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (
        Index("idx_user_campaigns_user", "user_id"),
        Index("idx_user_campaigns_campaign", "campaign_id"),
    )

    def __repr__(self) -> str:
        return f"<UserCampaign user={self.user_id} campaign={self.campaign_id}>"


class UserMetaConnection(Base):
    """Encrypted Meta OAuth access token for a dashboard user.

    One row per app user (``user_id`` is both PK and FK). The
    ``encrypted_access_token`` column is the output of
    :func:`src.dashboard.crypto.encrypt_token` — the DB never stores
    plaintext. Re-OAuth overwrites the row via
    :func:`src.db.queries.upsert_meta_connection`.

    ``token_expires_at`` is the absolute timestamp computed at exchange
    time from Meta's relative ``expires_in``. Phase F reads it to
    reject stale tokens at adapter construction time.
    """

    __tablename__ = "user_meta_connections"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    meta_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # Phase G — enumerated at OAuth callback time, one Graph API
    # roundtrip per connection. Stored as JSONB so the shape of
    # ``MetaAdAccountInfo`` / ``MetaPageInfo`` can evolve without a
    # migration. Python-side access returns ``list[dict]``; the
    # dashboard layer coerces back into Pydantic before surfacing to
    # the frontend.
    available_ad_accounts: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    available_pages: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'::jsonb"
    )
    # Auto-picked when the user has exactly one account / Page. If
    # they have many, NULL here and the import UI forces a choice.
    default_ad_account_id: Mapped[str | None] = mapped_column(Text)
    default_page_id: Mapped[str | None] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_user_meta_connections_meta_user_id", "meta_user_id"),)

    def __repr__(self) -> str:
        return f"<UserMetaConnection user={self.user_id} meta={self.meta_user_id}>"


class UsageLog(Base):
    """One row per billable event — LLM call, Meta API hit, email.

    Written by ``src.services.usage.log_llm_call`` and
    ``log_meta_call`` after every external call. Partitioned by
    ``recorded_at`` via a TimescaleDB hypertable (see migration
    007) so "usage for this user in the current month" queries
    stay cheap as row counts scale with traffic.

    FK columns are nullable with ``ON DELETE SET NULL`` —
    historical cost records survive user or campaign deletion.
    """

    __tablename__ = "usage_log"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default="uuid_generate_v4()",
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
        server_default="now()",
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    campaign_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
    )
    cycle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("test_cycles.id", ondelete="SET NULL"),
    )
    service: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(Text)
    input_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB)

    def __repr__(self) -> str:
        return f"<UsageLog service={self.service} agent={self.agent} cost=${self.cost_usd}>"


class MagicLinkConsumed(Base):
    """Ledger of already-used magic-link tokens.

    ``api_auth_verify`` inserts a row here keyed by the SHA-256 hash of
    the raw token before issuing a session cookie. An ``ON CONFLICT DO
    NOTHING`` insert that returns zero affected rows indicates replay of
    a previously-consumed link. Storing the hash (not the token) means a
    leaked DB dump can't be replayed.
    """

    __tablename__ = "magic_links_consumed"

    token_hash: Mapped[str] = mapped_column(Text, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )

    __table_args__ = (Index("idx_magic_links_consumed_at", "consumed_at"),)

    def __repr__(self) -> str:
        return f"<MagicLinkConsumed consumed_at={self.consumed_at}>"


class ApprovalQueueItem(Base):
    __tablename__ = "approval_queue"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, server_default="uuid_generate_v4()"
    )
    # Phase H: nullable because pause/scale proposals don't own a
    # variant row — they reference an existing deployment via the
    # ``action_payload['deployment_id']`` key. The partial CHECK
    # constraint on the table guarantees variant_id is still
    # present for ``new_variant`` / ``promote_winner`` rows.
    variant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("variants.id")
    )
    campaign_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False
    )
    genome_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    # Phase H: what kind of change this row is proposing. Defaults
    # to ``new_variant`` so pre-Phase-H rows keep their meaning
    # after the upgrade.
    action_type: Mapped[ApprovalActionType] = mapped_column(
        Enum(
            ApprovalActionType,
            name="approval_action_type",
            create_type=False,
        ),
        nullable=False,
        server_default="new_variant",
    )
    # Phase H: structured evidence + target pointers for
    # non-variant actions. Shape is documented per action_type on
    # the Pydantic models in ``src/models/approvals.py``.
    action_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer: Mapped[str | None] = mapped_column(Text)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    # Phase H: stamped by the approval executor once it has
    # actually pushed the side-effect to Meta. Gap between
    # ``approved=TRUE`` and ``executed_at IS NOT NULL`` is the
    # window where the DB says yes but the mutation hasn't
    # landed; the approve handler uses it for double-click
    # idempotency.
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    variant: Mapped[Variant | None] = relationship()
    campaign: Mapped[Campaign] = relationship()

    __table_args__ = (
        Index("idx_approval_pending", "campaign_id", postgresql_where="approved IS NULL"),
        Index(
            "idx_approval_pending_by_type",
            "campaign_id",
            "action_type",
            postgresql_where="approved IS NULL",
        ),
    )

    def __repr__(self) -> str:
        return f"<ApprovalQueueItem variant={self.variant_id} approved={self.approved}>"
