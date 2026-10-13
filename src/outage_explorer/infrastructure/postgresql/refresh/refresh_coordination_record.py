"""Map refresh coordination columns used by run reads and lease ownership."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from outage_explorer.infrastructure.postgresql.orm_base import Base


class RefreshCoordinationRecord(Base):
    __tablename__ = "refresh_coordination"

    singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True)
    active_run_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
    epoch: Mapped[int] = mapped_column(BigInteger)
    owner_identity: Mapped[str | None] = mapped_column(Text)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_generation_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False))
