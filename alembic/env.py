"""Alembic async environment configuration.

Configures Alembic to use the async SQLAlchemy engine from ``src.db.engine``
and imports all ORM models so autogenerate can detect schema changes.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from src.config import get_settings
from src.db.tables import Base  # noqa: F401 — imported for autogenerate metadata

# Alembic Config object, provides access to .ini values
config = context.config

# Set the SQLAlchemy URL from application settings, overriding alembic.ini.
# This ensures migrations always use the same connection string as the app.
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Standard Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations against the provided synchronous connection."""  # noqa: D401
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode using an async engine.

    Creates an async engine from the Alembic config, acquires a connection,
    and delegates to the synchronous ``do_run_migrations`` helper via
    ``run_sync``.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online migrations — delegates to the async runner."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
