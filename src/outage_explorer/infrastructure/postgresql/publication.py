"""Short, row-serialized refresh transactions and durable publication history."""

import json
from contextlib import AbstractContextManager

from outage_explorer.application.errors import (
    AccessStoreError,
)
from outage_explorer.application.ports.refresh import RefreshAdmissionTransaction
from outage_explorer.domain.publication import (
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    ResourcePublishedGeneration,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.published_generation_repository import (
    PostgresqlPublishedGenerationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_coordination_repository import (
    PostgresqlRefreshCoordinationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_run_repository import (
    PostgresqlRefreshRunRepository,
)


def _quality_payload(value: str | None) -> dict[str, object] | None:
    if value is None:
        return None
    if len(value.encode()) > 65536:
        raise ValueError("Refresh report exceeds bound")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid refresh report")
    return parsed


class PostgresqlResourcePublicationStore:
    """Fenced refresh coordination and exact resource publication (ADR-0064).

    Historical rows without exact descriptors remain unreadable. No conversion,
    pointer reset or publication-history deletion is performed by this adapter.
    """

    def __init__(
        self,
        pool: BoundedPostgresqlPool,
        runs: PostgresqlRefreshRunRepository,
        generations: PostgresqlPublishedGenerationRepository,
        coordination: PostgresqlRefreshCoordinationRepository,
    ) -> None:
        self._pool = pool
        self._runs = runs
        self._generations = generations
        self._coordination = coordination

    def replay(self, requester_id: str, key_digest: str) -> RefreshRun | None:
        return self._runs.replay(requester_id, key_digest)

    def admission_transaction(
        self,
    ) -> AbstractContextManager[RefreshAdmissionTransaction]:
        return self._runs.admission_transaction()

    def get_run(self, run_id: str) -> RefreshRun | None:
        return self._runs.get_run(run_id)

    def latest(self) -> RefreshRun | None:
        return self._runs.latest()

    def claim(self, identity: str, lease_seconds: int) -> RefreshOwner | None:
        return self._coordination.claim(identity, lease_seconds)

    def heartbeat(self, owner: RefreshOwner, lease_seconds: int) -> None:
        self._coordination.heartbeat(owner, lease_seconds)

    def progress(
        self, owner: RefreshOwner, stage: RefreshStage, quality_json: str | None = None
    ) -> None:
        if stage in {RefreshStage.QUEUED, RefreshStage.FINISHED}:
            raise ValueError("Invalid progress stage")
        self._coordination.progress(owner, stage, _quality_payload(quality_json))

    def finish(
        self,
        owner: RefreshOwner,
        status: RunStatus,
        quality_json: str | None = None,
        failure: str | None = None,
    ) -> RefreshRun:
        if status not in {RunStatus.FAILED, RunStatus.RETAINED}:
            raise ValueError("Invalid unpublished outcome")
        return self._coordination.finish(
            owner, status, _quality_payload(quality_json), failure
        )

    def _publish(
        self,
        owner: RefreshOwner,
        generation: ResourcePublishedGeneration,
        quality_json: str | None,
    ) -> RefreshRun:
        if generation.run_id != owner.run_id:
            raise ValueError("Generation run mismatch")
        quality = _quality_payload(quality_json)
        try:
            return self._generations.publish(owner, generation, quality)
        except AccessStoreError:
            # A new checkout serializes with the original transaction. Absence is
            # conclusive only after obtaining this same lock; failure is unavailable.
            return self._reconcile(owner.run_id, force=True)

    def recover(self, run_id: str) -> RefreshRun:
        return self._reconcile(run_id, force=False)

    def _reconcile(self, run_id: str, *, force: bool) -> RefreshRun:
        """Resolve publication first; force permits interruption before lease expiry."""
        return self._generations.reconcile(run_id, force=force)

    def active_generation(self) -> ResourcePublishedGeneration | None:
        return self._generations.active_generation()

    def generation_for_run(self, run_id: str) -> ResourcePublishedGeneration | None:
        with self._pool.connection() as connection:
            return self._generations.generation_for_run(connection, run_id)

    def publish(
        self,
        owner: RefreshOwner,
        generation: ResourcePublishedGeneration,
        quality_json: str | None = None,
    ) -> RefreshRun:
        generation.validate()
        return self._publish(owner, generation, quality_json)
