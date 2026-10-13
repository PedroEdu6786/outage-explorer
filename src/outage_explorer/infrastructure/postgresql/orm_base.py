"""Shared metadata for read mappings; Alembic remains the schema authority."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Partial read metadata, not for schema creation or autogeneration."""
