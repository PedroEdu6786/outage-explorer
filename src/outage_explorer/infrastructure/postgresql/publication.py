"""Short, row-serialized refresh transactions and durable publication history."""

import json
from dataclasses import asdict
from datetime import date
from uuid import uuid4

from psycopg import Connection
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb

from outage_explorer.application.errors import (
    AccessStoreError,
    IdempotencyConflictError,
    RefreshBusyError,
    StaleRefreshOwnerError,
)
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import (
    DatasetSummary,
    PublicationState,
    PublishedGeneration,
    RefreshConfiguration,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool


def _configuration(value: RefreshConfiguration) -> dict[str, object]:
    return asdict(value) | {
        "start": value.start.isoformat(),
        "end": value.end.isoformat(),
    }


def _run(row: DictRow) -> RefreshRun:
    config = row["configuration"]
    configuration = RefreshConfiguration(
        **(
            config
            | {
                "start": date.fromisoformat(config["start"]),
                "end": date.fromisoformat(config["end"]),
            }
        )
    )
    return RefreshRun(
        str(row["id"]),
        str(row["requester_id"]),
        row["key_digest"],
        row["request_identity"],
        configuration,
        str(row["base_generation_id"]) if row["base_generation_id"] else None,
        RunStatus(row["status"]),
        RefreshStage(row["stage"]),
        row["admitted_at"],
        row["updated_at"],
        row["epoch"],
        str(row["generation_id"]) if row["generation_id"] else None,
        PublicationState(row["publication"]),
        json.dumps(row["quality_json"], sort_keys=True)
        if row["quality_json"] is not None
        else None,
        row["failure"],
        row["no_publication_reason"],
        row["started_at"],
        row["finished_at"],
    )


def _generation(row: DictRow) -> PublishedGeneration:
    return PublishedGeneration(
        str(row["id"]),
        str(row["run_id"]),
        str(row["base_generation_id"]) if row["base_generation_id"] else None,
        row["manifest_key"],
        row["manifest_digest"],
        row["verification_version"],
        row["verified_at"],
        tuple(
            DatasetSummary(
                AnalyticalGrain(item["grain"]),
                item["schema_version"],
                item["rows"],
                date.fromisoformat(item["start"]),
                date.fromisoformat(item["end"]),
            )
            for item in row["datasets"]
        ),
    )


def _quality(value: str | None) -> Jsonb | None:
    if value is None:
        return None
    if len(value.encode()) > 65536:
        raise ValueError("Refresh report exceeds bound")
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid refresh report")
    return Jsonb(parsed)


class PostgresqlPublicationStore:
    def __init__(self, pool: BoundedPostgresqlPool) -> None:
        self._pool = pool

    def _lock(self, connection: Connection[DictRow]) -> DictRow:
        row = connection.execute(
            "SELECT *, lease_until > clock_timestamp() AS healthy FROM refresh_coordination WHERE singleton FOR UPDATE"
        ).fetchone()
        if row is None:
            raise AccessStoreError("Refresh coordination unavailable")
        return row

    def _owned(self, connection: Connection[DictRow], owner: RefreshOwner) -> DictRow:
        coordination = self._lock(connection)
        if (
            str(coordination["active_run_id"]),
            coordination["owner_identity"],
            coordination["epoch"],
            coordination["healthy"],
        ) != (owner.run_id, owner.identity, owner.epoch, True):
            raise StaleRefreshOwnerError("Refresh ownership expired")
        return coordination

    def _read(self, connection: Connection[DictRow], run_id: str) -> RefreshRun:
        row = connection.execute(
            "SELECT * FROM refresh_runs WHERE id = %s", (run_id,)
        ).fetchone()
        if row is None:
            raise ValueError("Refresh unavailable")
        return _run(row)

    def _replay(
        self,
        connection: Connection[DictRow],
        requester_id: str,
        key_digest: str,
        request_identity: str,
    ) -> RefreshRun | None:
        row = connection.execute(
            "SELECT * FROM refresh_runs WHERE requester_id = %s AND operation = 'refresh' AND key_digest = %s",
            (requester_id, key_digest),
        ).fetchone()
        if row is None:
            return None
        if row["request_identity"] != request_identity:
            raise IdempotencyConflictError("Idempotency key conflict")
        return _run(row)

    def replay(
        self, requester_id: str, key_digest: str, request_identity: str
    ) -> RefreshRun | None:
        with self._pool.connection() as connection:
            return self._replay(connection, requester_id, key_digest, request_identity)

    def admit(
        self,
        requester_id: str,
        key_digest: str,
        request_identity: str,
        configuration: RefreshConfiguration,
    ) -> RefreshRun:
        with self._pool.connection() as connection:
            coordination = self._lock(connection)
            replay = self._replay(
                connection, requester_id, key_digest, request_identity
            )
            if replay is not None:
                return replay
            if coordination["active_run_id"] is not None:
                raise RefreshBusyError("Refresh already admitted")
            configuration.validate(initial=coordination["active_generation_id"] is None)
            run_id = str(uuid4())
            connection.execute(
                "INSERT INTO refresh_runs(id, requester_id, key_digest, request_identity, configuration, base_generation_id, status, stage, publication) VALUES (%s,%s,%s,%s,%s,%s,'accepted','queued','pending')",
                (
                    run_id,
                    requester_id,
                    key_digest,
                    request_identity,
                    Jsonb(_configuration(configuration)),
                    coordination["active_generation_id"],
                ),
            )
            connection.execute(
                "UPDATE refresh_coordination SET active_run_id = %s WHERE singleton",
                (run_id,),
            )
            result = self._read(connection, run_id)
        return result

    def get_run(self, run_id: str) -> RefreshRun | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM refresh_runs WHERE id = %s", (run_id,)
            ).fetchone()
            return _run(row) if row else None

    def latest(self) -> RefreshRun | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT r.* FROM refresh_runs r CROSS JOIN refresh_coordination c ORDER BY (r.id = c.active_run_id) DESC NULLS LAST, r.admitted_at DESC, r.id DESC LIMIT 1"
            ).fetchone()
            return _run(row) if row else None

    def active_generation(self) -> PublishedGeneration | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT g.* FROM published_generations g JOIN refresh_coordination c ON c.active_generation_id = g.id"
            ).fetchone()
            return _generation(row) if row else None

    def generation_for_run(self, run_id: str) -> PublishedGeneration | None:
        with self._pool.connection() as connection:
            row = connection.execute(
                "SELECT * FROM published_generations WHERE run_id = %s", (run_id,)
            ).fetchone()
            return _generation(row) if row else None

    @staticmethod
    def _lease(identity: str, seconds: int) -> None:
        if (
            not identity
            or len(identity) > 256
            or type(seconds) is not int
            or not 1 <= seconds <= 300
        ):
            raise ValueError("Invalid refresh lease")

    def claim(self, identity: str, lease_seconds: int) -> RefreshOwner | None:
        self._lease(identity, lease_seconds)
        with self._pool.connection() as connection:
            coordination = self._lock(connection)
            if coordination["active_run_id"] is None:
                return None
            run = self._read(connection, str(coordination["active_run_id"]))
            if run.status is not RunStatus.ACCEPTED:
                return None
            epoch = coordination["epoch"] + 1
            connection.execute(
                "UPDATE refresh_coordination SET epoch = %s, owner_identity = %s, lease_until = clock_timestamp() + %s * interval '1 second' WHERE singleton",
                (epoch, identity, lease_seconds),
            )
            connection.execute(
                "UPDATE refresh_runs SET status = 'running', stage = 'retrieving', started_at = COALESCE(started_at, clock_timestamp()), epoch = %s, updated_at = clock_timestamp() WHERE id = %s",
                (epoch, run.id),
            )
            result = RefreshOwner(run.id, identity, epoch)
        return result

    def heartbeat(self, owner: RefreshOwner, lease_seconds: int) -> None:
        self._lease(owner.identity, lease_seconds)
        with self._pool.connection() as connection:
            self._owned(connection, owner)
            connection.execute(
                "UPDATE refresh_coordination SET lease_until = clock_timestamp() + %s * interval '1 second' WHERE singleton",
                (lease_seconds,),
            )

    def progress(
        self, owner: RefreshOwner, stage: RefreshStage, quality_json: str | None = None
    ) -> None:
        if stage in {RefreshStage.QUEUED, RefreshStage.FINISHED}:
            raise ValueError("Invalid progress stage")
        quality = _quality(quality_json)
        with self._pool.connection() as connection:
            self._owned(connection, owner)
            connection.execute(
                "UPDATE refresh_runs SET stage = %s, quality_json = COALESCE(%s, quality_json), updated_at = clock_timestamp() WHERE id = %s",
                (stage.value, quality, owner.run_id),
            )

    def finish(
        self,
        owner: RefreshOwner,
        status: RunStatus,
        quality_json: str | None = None,
        failure: str | None = None,
    ) -> RefreshRun:
        if status not in {RunStatus.FAILED, RunStatus.RETAINED}:
            raise ValueError("Invalid unpublished outcome")
        quality = _quality(quality_json)
        with self._pool.connection() as connection:
            self._owned(connection, owner)
            run = self._read(connection, owner.run_id)
            if status is RunStatus.RETAINED and run.base_generation_id is None:
                raise ValueError("Initial data cannot be retained")
            connection.execute(
                "UPDATE refresh_runs SET status = %s, publication = 'not_published', stage = 'finished', finished_at = clock_timestamp(), failure = %s, quality_json = COALESCE(%s, quality_json), no_publication_reason = %s, updated_at = clock_timestamp() WHERE id = %s",
                (
                    status.value,
                    failure,
                    quality,
                    "all_incoming_rows_excluded"
                    if status is RunStatus.RETAINED
                    else None,
                    owner.run_id,
                ),
            )
            self._release(connection)
            result = self._read(connection, owner.run_id)
        return result

    def _release(self, connection: Connection[DictRow]) -> None:
        connection.execute(
            "UPDATE refresh_coordination SET active_run_id = NULL, owner_identity = NULL, lease_until = NULL, epoch = epoch + 1 WHERE singleton"
        )

    def publish(
        self,
        owner: RefreshOwner,
        generation: PublishedGeneration,
        quality_json: str | None = None,
    ) -> RefreshRun:
        generation.validate()
        if generation.run_id != owner.run_id:
            raise ValueError("Generation run mismatch")
        quality = _quality(quality_json)
        try:
            with self._pool.connection() as connection:
                coordination = self._owned(connection, owner)
                run = self._read(connection, owner.run_id)
                active = (
                    str(coordination["active_generation_id"])
                    if coordination["active_generation_id"]
                    else None
                )
                if (
                    active != run.base_generation_id
                    or active != generation.base_generation_id
                ):
                    raise StaleRefreshOwnerError("Publication base changed")
                run.configuration.validate(initial=active is None)
                datasets = [
                    asdict(item)
                    | {"start": item.start.isoformat(), "end": item.end.isoformat()}
                    for item in generation.datasets
                ]
                connection.execute(
                    "INSERT INTO published_generations(id, run_id, base_generation_id, manifest_key, manifest_digest, verification_version, verified_at, datasets) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        generation.id,
                        generation.run_id,
                        generation.base_generation_id,
                        generation.manifest_key,
                        generation.manifest_digest,
                        generation.verification_version,
                        generation.verified_at,
                        Jsonb(datasets),
                    ),
                )
                connection.execute(
                    "UPDATE refresh_coordination SET active_generation_id = %s WHERE singleton",
                    (generation.id,),
                )
                connection.execute(
                    "UPDATE refresh_runs SET status = 'succeeded', publication = 'published', generation_id = %s, stage = 'finished', finished_at = clock_timestamp(), quality_json = COALESCE(%s, quality_json), updated_at = clock_timestamp() WHERE id = %s",
                    (generation.id, quality, owner.run_id),
                )
                self._release(connection)
                result = self._read(connection, owner.run_id)
            return result
        except AccessStoreError:
            # A new checkout serializes with the original transaction. Absence is
            # conclusive only after obtaining this same lock; failure is unavailable.
            return self._reconcile(owner.run_id, force=True)

    def recover(self, run_id: str) -> RefreshRun:
        return self._reconcile(run_id, force=False)

    def _reconcile(self, run_id: str, *, force: bool) -> RefreshRun:
        with self._pool.connection() as connection:
            coordination = self._lock(connection)
            run = self._read(connection, run_id)
            history = connection.execute(
                "SELECT * FROM published_generations WHERE run_id = %s", (run_id,)
            ).fetchone()
            if history is not None:
                if run.status is not RunStatus.SUCCEEDED:
                    connection.execute(
                        "UPDATE refresh_runs SET status = 'succeeded', publication = 'published', generation_id = %s, stage = 'finished', finished_at = clock_timestamp(), updated_at = clock_timestamp() WHERE id = %s",
                        (history["id"], run_id),
                    )
                if str(coordination["active_run_id"]) == run_id:
                    self._release(connection)
            elif (
                str(coordination["active_run_id"]) == run_id
                and run.status in {RunStatus.RUNNING, RunStatus.PUBLICATION_UNKNOWN}
                and (force or not coordination["healthy"])
            ):
                connection.execute(
                    "UPDATE refresh_runs SET status = 'interrupted', publication = 'not_published', stage = 'finished', finished_at = clock_timestamp(), failure = 'interrupted', updated_at = clock_timestamp() WHERE id = %s",
                    (run_id,),
                )
                self._release(connection)
            result = self._read(connection, run_id)
        return result
