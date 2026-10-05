"""Explicit, bounded and serialized operational schema setup."""

from collections.abc import Callable
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from outage_explorer.application.errors import AccessStoreError
from outage_explorer.infrastructure.postgresql.pool import validate_dsn

# Stable application-specific transaction lock; no other migration executor
# may read/write revision metadata before acquiring this same lock.
_MIGRATION_LOCK = 803079860865001


def run_migrations(
    dsn: str, *, password_provider: Callable[[], str] | None = None
) -> None:
    """Upgrade explicitly; a failure rolls back revision and product DDL together."""
    checked_dsn = validate_dsn(dsn)
    try:
        if password_provider is not None:
            from psycopg.conninfo import conninfo_to_dict, make_conninfo

            if "password" in conninfo_to_dict(checked_dsn):
                raise ValueError
            checked_dsn = make_conninfo(checked_dsn, password=password_provider())
        with psycopg.connect(
            checked_dsn,
            connect_timeout=5,
            options="-c statement_timeout=30000 -c lock_timeout=5000",
        ) as raw_connection:
            engine = create_engine(
                "postgresql+psycopg://",
                creator=lambda: raw_connection,
                poolclass=NullPool,
            )
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text("SELECT pg_advisory_xact_lock(:lock)"),
                        {"lock": _MIGRATION_LOCK},
                    )
                    config = Config(str(Path(__file__).with_name("alembic.ini")))
                    config.attributes["connection"] = connection
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
    except Exception:
        raise AccessStoreError("Schema migration failed") from None
