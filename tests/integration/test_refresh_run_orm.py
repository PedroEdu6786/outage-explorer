"""ORM reads coexist with existing transactions on disposable PostgreSQL."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from psycopg.types.json import Jsonb

from outage_explorer.application.errors import AccessStoreError
from outage_explorer.application.refresh_request import RefreshAdmissionRequest
from outage_explorer.domain.access import Role
from outage_explorer.domain.publication import RefreshRun, RefreshStage, RunStatus
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlResourcePublicationStore,
)
from outage_explorer.infrastructure.postgresql.published_generation_repository import (
    PostgresqlPublishedGenerationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_coordination_repository import (
    PostgresqlRefreshCoordinationRepository,
)
from outage_explorer.infrastructure.postgresql.refresh_run_repository import (
    PostgresqlRefreshRunRepository,
)
from tests.integration import test_data_api_postgresql as coordination

database = coordination.database
system = coordination.system
QUALITY = '{"national": {"selected": 2}, "warnings": []}'


def admit(system, key="a"):
    _, service, tokens, _, _ = system
    return service.admit(
        service.authorize(tokens[Role.ADMIN]),
        RefreshAdmissionRequest(idempotency_key=key * 16),
    )


@pytest.mark.parametrize(
    "status",
    [
        RunStatus.ACCEPTED,
        RunStatus.RUNNING,
        RunStatus.SUCCEEDED,
        RunStatus.FAILED,
        RunStatus.RETAINED,
        RunStatus.INTERRUPTED,
    ],
)
def test_read_matches_complete_committed_domain_value(system, status):
    store, _, _, _, pool = system
    if status is RunStatus.RETAINED:
        base = admit(system, "b")
        store.publish(store.claim("base", 60), coordination.candidate(base))

    run = admit(system)
    if status is not RunStatus.ACCEPTED:
        owner = store.claim("reader-test", 60)
        store.progress(owner, RefreshStage.VERIFYING, QUALITY)
        if status is RunStatus.SUCCEEDED:
            store.publish(owner, coordination.candidate(run), QUALITY)
        elif status is RunStatus.FAILED:
            store.finish(owner, status, QUALITY, failure="retrieval")
        elif status is RunStatus.RETAINED:
            store.finish(owner, status, QUALITY)
        elif status is RunStatus.INTERRUPTED:
            with pool.connection() as connection:
                connection.execute(
                    "UPDATE refresh_coordination SET lease_until = clock_timestamp() - interval '1 second'"
                )
            store.recover(run.id)

    expected = store.get_run(run.id)
    actual = PostgresqlRefreshRunRepository(pool).get_run(run.id)
    pool.close()

    assert type(actual) is RefreshRun
    assert actual == expected
    assert actual.status is status
    assert actual.configuration == coordination.CONFIG
    assert actual.admitted_at.utcoffset().total_seconds() == 0


def test_missing_run_and_repeated_reads_observe_committed_changes(system):
    store = system[0]
    assert store.get_run(str(uuid4())) is None
    admitted = admit(system)
    assert store.get_run(run_id=admitted.id) == admitted

    owner = store.claim("fresh-read", 60)
    assert store.get_run(admitted.id).status is RunStatus.RUNNING

    finished = store.finish(owner, RunStatus.FAILED, QUALITY, failure="retrieval")
    assert store.get_run(admitted.id) == finished


def test_concurrent_orm_and_raw_reads_share_bounded_pool(system):
    store, _, _, _, pool = system
    run = admit(system)

    def read(index):
        if index % 2:
            return store.get_run(run.id).id
        with pool.connection() as connection:
            return str(
                connection.execute(
                    "SELECT id FROM refresh_runs WHERE id = %s", (run.id,)
                ).fetchone()["id"]
            )

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert list(executor.map(read, range(80))) == [run.id] * 80
    assert pool._get_pool().get_stats()["pool_size"] <= 4


def test_query_errors_are_sanitized_and_release_all_connections(system, caplog):
    store, _, _, _, pool = system
    run = admit(system)
    for _ in range(8):
        with pytest.raises(AccessStoreError, match="^PostgreSQL operation failed$"):
            store.get_run("PRIVATE-invalid-uuid")

    assert "PRIVATE-invalid-uuid" not in caplog.text
    assert store.get_run(run.id) == run
    # Every slot can still be borrowed, with the raw adapter's dictionary rows.
    with ExitStack() as stack:
        connections = [stack.enter_context(pool.connection()) for _ in range(4)]
        for connection in connections:
            assert connection.execute("SELECT 1 AS ready").fetchone() == {"ready": 1}


def test_caller_exception_rolls_back_orm_transaction(system):
    store, _, _, _, pool = system
    run = admit(system)
    from sqlalchemy import update

    from outage_explorer.infrastructure.postgresql.refresh_run_record import (
        RefreshRunRecord,
    )

    with pytest.raises(ValueError, match="controlled failure"):
        with pool.session() as session:
            session.execute(
                update(RefreshRunRecord)
                .where(RefreshRunRecord.id == run.id)
                .values(stage="retrieving")
            )
            raise ValueError("controlled failure")
    assert store.get_run(run.id) == run


def test_orm_construction_is_lazy_and_reads_reject_fork_or_close(monkeypatch):
    def unexpected_connect(*args, **kwargs):
        pytest.fail("Unexpected database connection")

    monkeypatch.setattr("psycopg.Connection.connect", unexpected_connect)
    pool = BoundedPostgresqlPool("host=127.0.0.1 dbname=unused")
    store = PostgresqlResourcePublicationStore(
        pool,
        PostgresqlRefreshRunRepository(pool),
        PostgresqlPublishedGenerationRepository(pool),
        PostgresqlRefreshCoordinationRepository(pool),
    )
    assert pool._pool is None
    with monkeypatch.context() as fork:
        fork.setattr("os.getpid", lambda: -1)
        with pytest.raises(AccessStoreError, match="cross processes"):
            store.get_run(str(uuid4()))
    assert pool._owner == os.getpid()
    pool.close()
    with pytest.raises(AccessStoreError, match="closed"):
        store.get_run(str(uuid4()))


def test_latest_returns_none_when_no_runs_exist(system):
    store, _, _, _, pool = system
    assert PostgresqlRefreshRunRepository(pool).latest() is None
    assert store.latest() is None


@pytest.mark.parametrize(
    "active_number,hours,has_coordination,expected_number",
    [
        (1, (1, 3, 2), True, 1),  # An older active run takes priority.
        (None, (1, 3, 2), True, 2),  # Timestamp takes priority over UUID.
        (None, (1, 3, 3), True, 3),  # UUID breaks timestamp ties.
        (None, (1, 3, 2), False, None),  # Preserve the original inner join.
    ],
)
def test_latest_preserves_ordering_and_observes_pointer_changes(
    system, active_number, hours, has_coordination, expected_number
):
    store, _, _, users, pool = system
    ids = {number: f"00000000-0000-0000-0000-{number:012d}" for number in (1, 2, 3)}
    with pool.connection() as connection:
        for number, hour in enumerate(hours, start=1):
            active = number == active_number
            connection.execute(
                """
                INSERT INTO refresh_runs (
                    id, requester_id, key_digest, configuration,
                    status, stage, publication, admitted_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    ids[number],
                    users[Role.ADMIN].id,
                    str(number) * 64,
                    Jsonb(coordination.CONFIG.model_dump(mode="json")),
                    "accepted" if active else "failed",
                    "queued" if active else "finished",
                    "pending" if active else "not_published",
                    datetime(2026, 10, 12, hour, tzinfo=UTC),
                ),
            )
        if has_coordination:
            connection.execute(
                "UPDATE refresh_coordination SET active_run_id = %s",
                (ids.get(active_number),),
            )
        else:
            connection.execute("DELETE FROM refresh_coordination")

    repository = PostgresqlRefreshRunRepository(pool)
    latest = repository.latest()
    assert (latest.id if latest else None) == ids.get(expected_number)
    assert store.latest() == latest

    if active_number is not None:
        owner = store.claim("latest-test", 60)
        store.finish(owner, RunStatus.FAILED, failure="retrieval")
        # The same repository must observe the released pointer on its next call.
        assert repository.latest().id == ids[2]
