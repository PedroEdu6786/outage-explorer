"""Map immutable published generations; Alembic owns the schema."""

from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from outage_explorer.application.errors import UnsupportedPublicationLayoutError
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.postgresql.orm_base import Base


def resource_generation_from_values(
    generation_id: object,
    run_id: object,
    base_generation_id: object | None,
    verification_version: str,
    verified_at: datetime,
    datasets: list[dict[str, Any]],
) -> ResourcePublishedGeneration:
    """Convert stored descriptors for both ORM and existing psycopg reads."""
    try:
        summaries = tuple(
            DatasetSummary(
                AnalyticalGrain(item["grain"]),
                item["schema_version"],
                item["rows"],
                date.fromisoformat(item["start"]),
                date.fromisoformat(item["end"]),
                item["object_key"],
                item["sha256"],
                item["byte_count"],
            )
            for item in datasets
        )
        generation = ResourcePublishedGeneration(
            str(generation_id),
            str(run_id),
            str(base_generation_id) if base_generation_id else None,
            verification_version,
            verified_at,
            summaries,
        )
        generation.validate()
    except (KeyError, TypeError, ValueError):
        raise UnsupportedPublicationLayoutError(
            "Stored publication descriptors are invalid"
        ) from None
    return generation


class PublishedGenerationRecord(Base):
    __tablename__ = "published_generations"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    run_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    base_generation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    verification_version: Mapped[str] = mapped_column(Text)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    datasets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)

    @classmethod
    def from_domain(
        cls, generation: ResourcePublishedGeneration
    ) -> "PublishedGenerationRecord":
        return cls(
            id=generation.id,
            run_id=generation.run_id,
            base_generation_id=generation.base_generation_id,
            verification_version=generation.verification_version,
            verified_at=generation.verified_at,
            datasets=[
                asdict(item)
                | {"start": item.start.isoformat(), "end": item.end.isoformat()}
                for item in generation.datasets
            ],
        )

    def to_domain(self) -> ResourcePublishedGeneration:
        return resource_generation_from_values(
            self.id,
            self.run_id,
            self.base_generation_id,
            self.verification_version,
            self.verified_at,
            self.datasets,
        )
