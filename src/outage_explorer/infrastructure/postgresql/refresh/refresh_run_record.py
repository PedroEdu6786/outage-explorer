"""Map refresh runs for reads and ownership updates; Alembic owns the schema."""

import json
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from outage_explorer.domain.publication import (
    PublicationState,
    RefreshConfiguration,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.orm_base import Base


class RefreshRunRecord(Base):
    __tablename__ = "refresh_runs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    requester_id: Mapped[str] = mapped_column(UUID(as_uuid=False))
    key_digest: Mapped[str] = mapped_column(Text)
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB)
    base_generation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    status: Mapped[str] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(Text)
    admitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
    epoch: Mapped[int | None] = mapped_column(BigInteger)
    generation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    publication: Mapped[str] = mapped_column(Text)
    quality_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    failure: Mapped[str | None] = mapped_column(Text)
    no_publication_reason: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def to_domain(self) -> RefreshRun:
        """Copy loaded columns into a domain value before the session closes."""
        quality_json = (
            json.dumps(self.quality_json, sort_keys=True)
            if self.quality_json is not None
            else None
        )
        return RefreshRun(
            id=self.id,
            requester_id=self.requester_id,
            key_digest=self.key_digest,
            configuration=RefreshConfiguration.model_validate_json(
                json.dumps(self.configuration)
            ),
            base_generation_id=self.base_generation_id,
            status=RunStatus(self.status),
            stage=RefreshStage(self.stage),
            admitted_at=self.admitted_at,
            epoch=self.epoch,
            generation_id=self.generation_id,
            publication=PublicationState(self.publication),
            quality_json=quality_json,
            failure=self.failure,
            no_publication_reason=self.no_publication_reason,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )
