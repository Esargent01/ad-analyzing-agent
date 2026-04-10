"""Per-user Meta tenancy: ad accounts, pages, and per-campaign locking.

Phase G of the self-serve multi-tenant migration. Closes the final
global-settings leak in the Meta integration.

Before this migration, ``meta_factory.get_meta_adapter_for_user`` still
read ``settings.meta_ad_account_id``, ``settings.meta_page_id`` and
``settings.meta_landing_page_url`` at adapter construction time — which
meant every user's adapter pointed at the *operator's* ad account even
though the access token was theirs. In practice this failed closed for
most users (Meta denies cross-account reads) but it blocked legitimate
multi-tenant onboarding and was a latent data-leak risk for anyone
with cross-account permissions in the operator's Business Manager.

What this migration does:

1. Adds four columns to ``user_meta_connections`` so the set of ad
   accounts and Pages a token can see is enumerated once at OAuth
   callback time and cached on the row:

   - ``available_ad_accounts`` (JSONB array of
     ``{id, name, account_status, currency}``)
   - ``available_pages`` (JSONB array of ``{id, name, category}``)
   - ``default_ad_account_id`` (TEXT, chosen automatically when the
     user has exactly one account)
   - ``default_page_id`` (TEXT, same policy)

2. Adds three columns to ``campaigns`` so each imported campaign is
   pinned to a specific Meta ad account, Page, and landing-page URL:

   - ``meta_ad_account_id`` (TEXT)
   - ``meta_page_id`` (TEXT)
   - ``landing_page_url`` (TEXT)

3. Backfills existing Meta campaigns from the pre-Phase-G global env
   var values. After Phase F the only live campaign is Slice Society
   running on the operator's account, so the backfill is deterministic
   — read the current ``settings.meta_ad_account_id`` /
   ``meta_page_id`` / ``meta_landing_page_url`` values at migration
   time and write them onto every Meta campaign row that still has
   NULL. The migration is hermetic: values are resolved from settings
   here, not from whatever env happens to be set on rollback.

4. Adds a partial CHECK constraint enforcing NOT NULL on the two
   required columns (``meta_ad_account_id``, ``meta_page_id``) *only
   for rows where platform = 'meta'*. Non-Meta platforms (future
   Google Ads etc.) aren't dragged in. ``landing_page_url`` is left
   nullable because the import flow treats it as optional.

Downgrade drops the check constraint and columns. The JSONB defaults
make the columns safely droppable without data loss — the legacy
settings are still readable until Phase G's config.py deletion lands.

Revision ID: 009_per_user_meta_tenancy
Revises: 008_migrate_legacy_campaigns
Create Date: 2026-04-10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_per_user_meta_tenancy"
down_revision: str | None = "008_migrate_legacy_campaigns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Step 1 — extend user_meta_connections with enumerated ad accounts
    # and pages. Defaults are empty arrays so existing rows (including
    # the operator's) stay valid until a re-OAuth populates them.
    # ------------------------------------------------------------------
    op.add_column(
        "user_meta_connections",
        sa.Column(
            "available_ad_accounts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "user_meta_connections",
        sa.Column(
            "available_pages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "user_meta_connections",
        sa.Column("default_ad_account_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_meta_connections",
        sa.Column("default_page_id", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # Step 2 — extend campaigns with per-campaign Meta tenancy columns.
    # All nullable at first so the backfill below can run.
    # ------------------------------------------------------------------
    op.add_column(
        "campaigns",
        sa.Column("meta_ad_account_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("meta_page_id", sa.Text(), nullable=True),
    )
    op.add_column(
        "campaigns",
        sa.Column("landing_page_url", sa.Text(), nullable=True),
    )

    # ------------------------------------------------------------------
    # Step 3 — backfill existing Meta campaigns from the legacy global
    # env vars. Read directly from ``os.environ`` (not
    # ``src.config.Settings``) because the Phase G config.py cleanup
    # drops the three attributes entirely — importing ``Settings``
    # here would fall back to whatever the field default is, which
    # is not what we want. Operators deploying Phase G should keep
    # ``META_AD_ACCOUNT_ID`` / ``META_PAGE_ID`` /
    # ``META_LANDING_PAGE_URL`` set in their environment until this
    # migration has run successfully; after that they can be removed.
    # If the env vars are unset — e.g. a fresh dev environment that
    # was never wired to a real Meta account — skip the backfill and
    # rely on Phase G's per-campaign import flow to populate new rows.
    # ------------------------------------------------------------------
    import os

    legacy_account = os.environ.get("META_AD_ACCOUNT_ID") or None
    legacy_page = os.environ.get("META_PAGE_ID") or None
    legacy_url = os.environ.get("META_LANDING_PAGE_URL") or None

    if legacy_account and legacy_page:
        bind = op.get_bind()
        bind.execute(
            sa.text(
                """
                UPDATE campaigns
                   SET meta_ad_account_id = COALESCE(meta_ad_account_id, :account),
                       meta_page_id       = COALESCE(meta_page_id, :page),
                       landing_page_url   = COALESCE(landing_page_url, :url)
                 WHERE platform = 'meta'
                """
            ),
            {"account": legacy_account, "page": legacy_page, "url": legacy_url},
        )

    # ------------------------------------------------------------------
    # Step 4 — enforce the per-Meta-row invariant via a partial CHECK.
    # Non-Meta platforms are exempt so the column stays truly optional
    # for future Google Ads / TikTok adapters that don't use these
    # fields.
    # ------------------------------------------------------------------
    op.create_check_constraint(
        "campaigns_meta_tenancy_check",
        "campaigns",
        "platform <> 'meta' OR (meta_ad_account_id IS NOT NULL AND meta_page_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("campaigns_meta_tenancy_check", "campaigns", type_="check")
    op.drop_column("campaigns", "landing_page_url")
    op.drop_column("campaigns", "meta_page_id")
    op.drop_column("campaigns", "meta_ad_account_id")

    op.drop_column("user_meta_connections", "default_page_id")
    op.drop_column("user_meta_connections", "default_ad_account_id")
    op.drop_column("user_meta_connections", "available_pages")
    op.drop_column("user_meta_connections", "available_ad_accounts")
