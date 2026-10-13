"""Atomic refresh ownership operations over the coordination row."""

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.domain.publication import (
    PublicationState,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.refresh.refresh_coordination_record import (
    RefreshCoordinationRecord,
)
from outage_explorer.infrastructure.postgresql.refresh.refresh_run_record import (
    RefreshRunRecord,
)
from outage_explorer.infrastructure.postgresql.session_scope import with_session


def _valid_lease(identity: str, seconds: int) -> None:
    if (
        not identity
        or len(identity) > 256
        or type(seconds) is not int
        or not 1 <= seconds <= 300
    ):
        raise ValueError("Invalid refresh lease")


class PostgresqlRefreshCoordinationRepository:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    @staticmethod
    def _lock(session: Session) -> tuple[RefreshCoordinationRecord, bool | None]:
        healthy = RefreshCoordinationRecord.lease_until > func.clock_timestamp()
        query = (
            select(RefreshCoordinationRecord, healthy)
            .where(RefreshCoordinationRecord.singleton.is_(True))
            .with_for_update()
        )
        row = session.execute(query).one_or_none()
        if row is None:
            raise AccessStoreError("Refresh coordination unavailable")
        return row[0], row[1]

    @classmethod
    def assert_owned_in_transaction(
        cls, session: Session, owner: RefreshOwner
    ) -> RefreshCoordinationRecord:
        coordination, healthy = cls._lock(session)
        if (
            coordination.active_run_id,
            coordination.owner_identity,
            coordination.epoch,
            healthy,
        ) != (owner.run_id, owner.identity, owner.epoch, True):
            raise StaleRefreshOwnerError("Refresh ownership expired")
        return coordination

    @with_session
    def claim(
        self, session: Session, identity: str, lease_seconds: int
    ) -> RefreshOwner | None:
        _valid_lease(identity, lease_seconds)
        coordination, _ = self._lock(session)
        if coordination.active_run_id is None:
            return None

        run = session.get(RefreshRunRecord, coordination.active_run_id)
        if run is None:
            raise ValueError("Refresh unavailable")
        if run.status != RunStatus.ACCEPTED:
            return None

        epoch = coordination.epoch + 1
        session.execute(
            update(RefreshCoordinationRecord)
            .where(RefreshCoordinationRecord.singleton.is_(True))
            .values(
                epoch=epoch,
                owner_identity=identity,
                lease_until=func.clock_timestamp() + timedelta(seconds=lease_seconds),
            )
        )
        session.execute(
            update(RefreshRunRecord)
            .where(RefreshRunRecord.id == run.id)
            .values(
                status=RunStatus.RUNNING.value,
                stage="retrieving",
                started_at=func.coalesce(
                    RefreshRunRecord.started_at, func.clock_timestamp()
                ),
                epoch=epoch,
            )
        )
        return RefreshOwner(run.id, identity, epoch)

    @with_session
    def heartbeat(
        self, session: Session, owner: RefreshOwner, lease_seconds: int
    ) -> None:
        _valid_lease(owner.identity, lease_seconds)
        self.assert_owned_in_transaction(session, owner)

        session.execute(
            update(RefreshCoordinationRecord)
            .where(RefreshCoordinationRecord.singleton.is_(True))
            .values(
                lease_until=func.clock_timestamp() + timedelta(seconds=lease_seconds)
            )
        )

    @with_session
    def progress(
        self,
        session: Session,
        owner: RefreshOwner,
        stage: RefreshStage,
        quality: dict[str, object] | None,
    ) -> None:
        self.assert_owned_in_transaction(session, owner)
        changes: dict[str, object] = {"stage": stage.value}
        if quality is not None:
            changes["quality_json"] = quality
        session.execute(
            update(RefreshRunRecord)
            .where(RefreshRunRecord.id == owner.run_id)
            .values(**changes)
        )

    @with_session
    def finish(
        self,
        session: Session,
        owner: RefreshOwner,
        status: RunStatus,
        quality: dict[str, object] | None,
        failure: str | None,
    ) -> RefreshRun:
        coordination = self.assert_owned_in_transaction(session, owner)
        run = session.get(RefreshRunRecord, owner.run_id)
        if run is None:
            raise ValueError("Refresh unavailable")
        if status is RunStatus.RETAINED and run.base_generation_id is None:
            raise ValueError("Initial data cannot be retained")

        changes: dict[str, object] = {
            "status": status.value,
            "publication": PublicationState.NOT_PUBLISHED.value,
            "stage": RefreshStage.FINISHED.value,
            "finished_at": func.clock_timestamp(),
            "failure": failure,
            "no_publication_reason": (
                "all_incoming_rows_excluded" if status is RunStatus.RETAINED else None
            ),
        }
        if quality is not None:
            changes["quality_json"] = quality
        session.execute(
            update(RefreshRunRecord)
            .where(RefreshRunRecord.id == owner.run_id)
            .values(**changes)
        )

        coordination.active_run_id = None
        coordination.owner_identity = None
        coordination.lease_until = None
        coordination.epoch += 1
        session.flush()
        session.refresh(run)
        return run.to_domain()
