"""Published generation queries and atomic publication persistence."""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from outage_explorer.application.errors import (
    StaleRefreshOwnerError,
    UnsupportedPublicationLayoutError,
)
from outage_explorer.domain.publication import (
    PublicationState,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    ResourcePublishedGeneration,
    RunStatus,
)
from outage_explorer.domain.publication_policy import (
    PublicationBaseChangedError,
    require_publishable_base,
    should_interrupt_unpublished_run,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.refresh.published_generation_record import (
    PublishedGenerationRecord,
)
from outage_explorer.infrastructure.postgresql.refresh.refresh_coordination_record import (
    RefreshCoordinationRecord,
)
from outage_explorer.infrastructure.postgresql.refresh.refresh_coordination_repository import (
    PostgresqlRefreshCoordinationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh.refresh_run_record import (
    RefreshRunRecord,
)
from outage_explorer.infrastructure.postgresql.session_scope import with_session


class PostgresqlPublishedGenerationRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @staticmethod
    def check_base_in_transaction(session: Session, generation_id: str | None) -> None:
        if generation_id is None:
            return
        record = session.get(PublishedGenerationRecord, generation_id)
        if record is None:
            raise UnsupportedPublicationLayoutError(
                "Active publication layout is unsupported"
            )
        record.to_domain()

    @with_session
    def publish(
        self,
        session: Session,
        owner: RefreshOwner,
        generation: ResourcePublishedGeneration,
        quality: dict[str, object] | None,
    ) -> RefreshRun:
        coordination = (
            PostgresqlRefreshCoordinationRepository.assert_owned_in_transaction(
                session, owner
            )
        )
        run = session.get(RefreshRunRecord, owner.run_id)
        if run is None:
            raise ValueError("Refresh unavailable")

        active = coordination.active_generation_id
        try:
            require_publishable_base(run.to_domain(), generation, active)
        except PublicationBaseChangedError:
            raise StaleRefreshOwnerError("Publication base changed") from None
        self.check_base_in_transaction(session, active)

        session.add(PublishedGenerationRecord.from_domain(generation))
        session.flush()

        changes: dict[str, object] = {
            "status": RunStatus.SUCCEEDED.value,
            "publication": PublicationState.PUBLISHED.value,
            "generation_id": generation.id,
            "stage": RefreshStage.FINISHED.value,
            "finished_at": func.clock_timestamp(),
        }
        if quality is not None:
            changes["quality_json"] = quality
        session.execute(
            update(RefreshRunRecord)
            .where(RefreshRunRecord.id == owner.run_id)
            .values(**changes)
        )
        coordination.active_generation_id = generation.id
        coordination.active_run_id = None
        coordination.owner_identity = None
        coordination.lease_until = None
        coordination.epoch += 1
        session.flush()
        session.refresh(run)
        return run.to_domain()

    @with_session
    def active_generation(self, session: Session) -> ResourcePublishedGeneration | None:
        record = session.scalar(
            select(PublishedGenerationRecord).join(
                RefreshCoordinationRecord,
                RefreshCoordinationRecord.active_generation_id
                == PublishedGenerationRecord.id,
            )
        )
        return record.to_domain() if record is not None else None

    @with_session
    def reconcile(self, session: Session, run_id: str, *, force: bool) -> RefreshRun:
        """Reconcile publication and ownership under one coordination lock."""
        coordination, healthy = PostgresqlRefreshCoordinationRepository._lock(session)
        run = session.get(RefreshRunRecord, run_id)
        if run is None:
            raise ValueError("Refresh unavailable")

        generation_id = session.scalar(
            select(PublishedGenerationRecord.id).where(
                PublishedGenerationRecord.run_id == run_id
            )
        )
        is_active_run = coordination.active_run_id == run_id

        if generation_id is not None:
            if run.status != RunStatus.SUCCEEDED.value:
                session.execute(
                    update(RefreshRunRecord)
                    .where(RefreshRunRecord.id == run_id)
                    .values(
                        status=RunStatus.SUCCEEDED.value,
                        publication=PublicationState.PUBLISHED.value,
                        generation_id=generation_id,
                        stage=RefreshStage.FINISHED.value,
                        finished_at=func.clock_timestamp(),
                    )
                )
            if is_active_run:
                self._release_recovered_slot(coordination)
        elif should_interrupt_unpublished_run(
            run.to_domain(),
            is_active_run=is_active_run,
            lease_is_healthy=healthy,
            force=force,
        ):
            session.execute(
                update(RefreshRunRecord)
                .where(RefreshRunRecord.id == run_id)
                .values(
                    status=RunStatus.INTERRUPTED.value,
                    publication=PublicationState.NOT_PUBLISHED.value,
                    stage=RefreshStage.FINISHED.value,
                    finished_at=func.clock_timestamp(),
                    failure="interrupted",
                )
            )
            self._release_recovered_slot(coordination)

        session.flush()
        session.refresh(run)
        return run.to_domain()

    @staticmethod
    def _release_recovered_slot(coordination: RefreshCoordinationRecord) -> None:
        coordination.active_run_id = None
        coordination.owner_identity = None
        coordination.lease_until = None
        coordination.epoch += 1

    @with_session
    def generation_for_run(
        self, session: Session, run_id: str
    ) -> ResourcePublishedGeneration | None:
        record = session.scalar(
            select(PublishedGenerationRecord).where(
                PublishedGenerationRecord.run_id == run_id
            )
        )
        return record.to_domain() if record is not None else None
