"""ORM queries for refresh runs, returning database-independent domain values."""

from collections.abc import Generator
from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import select, true
from sqlalchemy.orm import Session

from outage_explorer.domain.publication import (
    PublicationState,
    RefreshConfiguration,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.published_generation_repository import (
    PostgresqlPublishedGenerationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_coordination_record import (
    RefreshCoordinationRecord,
)
from outage_explorer.infrastructure.postgresql.refresh_coordination_repository import (
    PostgresqlRefreshCoordinationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_run_record import (
    RefreshRunRecord,
)
from outage_explorer.infrastructure.postgresql.session_scope import with_session


class PostgresqlRefreshAdmissionTransaction:
    """Persistence operations sharing the admission coordination lock."""

    def __init__(
        self, session: Session, coordination: RefreshCoordinationRecord
    ) -> None:
        self._session = session
        self._coordination = coordination

    @property
    def active_run_id(self) -> str | None:
        return self._coordination.active_run_id

    @property
    def base_generation_id(self) -> str | None:
        return self._coordination.active_generation_id

    def replay(self, requester_id: str, key_digest: str) -> RefreshRun | None:
        record = PostgresqlRefreshRunRepository._replay_in_transaction(
            self._session, requester_id, key_digest
        )
        return record.to_domain() if record is not None else None

    def require_supported_base(self) -> None:
        PostgresqlPublishedGenerationRepository.check_base_in_transaction(
            self._session, self.base_generation_id
        )

    def create_queued_run(
        self,
        requester_id: str,
        key_digest: str,
        configuration: RefreshConfiguration,
    ) -> RefreshRun:
        run = RefreshRunRecord(
            id=str(uuid4()),
            requester_id=requester_id,
            key_digest=key_digest,
            configuration=configuration.model_dump(mode="json"),
            base_generation_id=self.base_generation_id,
            status=RunStatus.ACCEPTED.value,
            stage=RefreshStage.QUEUED.value,
            publication=PublicationState.PENDING.value,
        )
        self._session.add(run)
        self._session.flush()
        self._coordination.active_run_id = run.id
        self._session.flush()
        self._session.refresh(run)
        return run.to_domain()


class PostgresqlRefreshRunRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @staticmethod
    def _replay_in_transaction(
        session: Session, requester_id: str, key_digest: str
    ) -> RefreshRunRecord | None:
        return session.scalar(
            select(RefreshRunRecord).where(
                RefreshRunRecord.requester_id == requester_id,
                RefreshRunRecord.key_digest == key_digest,
            )
        )

    @with_session
    def replay(
        self, session: Session, requester_id: str, key_digest: str
    ) -> RefreshRun | None:
        record = self._replay_in_transaction(session, requester_id, key_digest)
        return record.to_domain() if record is not None else None

    @contextmanager
    def admission_transaction(self) -> Generator[PostgresqlRefreshAdmissionTransaction]:
        """Hold one session across the service's admission decision and write."""
        with self._pool.session() as session:
            coordination, _ = PostgresqlRefreshCoordinationRepository._lock(session)
            yield PostgresqlRefreshAdmissionTransaction(session, coordination)

    @with_session
    def get_run(self, session: Session, run_id: str) -> RefreshRun | None:
        record = session.get(RefreshRunRecord, run_id)
        return record.to_domain() if record is not None else None

    @with_session
    def latest(self, session: Session) -> RefreshRun | None:
        is_active_run = RefreshRunRecord.id == RefreshCoordinationRecord.active_run_id
        query = (
            select(RefreshRunRecord)
            .join(RefreshCoordinationRecord, true())
            .order_by(
                is_active_run.desc().nulls_last(),
                RefreshRunRecord.admitted_at.desc(),
                RefreshRunRecord.id.desc(),
            )
            .limit(1)
        )
        record = session.scalar(query)
        return record.to_domain() if record is not None else None
