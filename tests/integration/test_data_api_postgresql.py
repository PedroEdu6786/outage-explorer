"""Disposable PostgreSQL races, publication fencing and commit-loss evidence."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import (
    AccessStoreError,
    ForbiddenError,
    IdempotencyConflictError,
    InvalidRequestError,
    RefreshBusyError,
    StaleRefreshOwnerError,
)
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.refresh import RefreshService
from outage_explorer.domain.access import AnalyticalGrain, Role
from outage_explorer.domain.publication import (
    INITIAL_END,
    INITIAL_START,
    DatasetSummary,
    PublishedGeneration,
    RefreshConfiguration,
    RefreshStage,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.migrations import run_migrations
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlPublicationStore,
)
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.settings import refresh_settings

CONFIG = RefreshConfiguration(INITIAL_START, INITIAL_END, 183, 183, 183, 1800, 1800)


@pytest.fixture
def database():
    admin = os.environ.get("OUTAGE_TEST_POSTGRES_DSN")
    if not admin:
        pytest.skip("Requires explicit disposable local PostgreSQL")
    values = conninfo_to_dict(admin)
    if (
        values.get("host") not in {"localhost", "127.0.0.1", "::1"}
        or "hostaddr" in values
    ):
        pytest.fail("Tests require loopback PostgreSQL")
    name = "data_api_test_" + uuid4().hex
    with psycopg.connect(admin, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(admin, dbname=name)
    try:
        run_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def system(database):
    pool = BoundedPostgresqlPool(database)
    access_store = PostgresqlAccessStore(pool)
    security = RandomSecurityMaterial()
    now = datetime.now(UTC)

    class Clock:
        def now(self):
            return now

    from datetime import timedelta

    tokens, users = {}, {}
    for role in Role:
        access_store.seed(
            (
                SeedIdentity(
                    "https://identity.example.test",
                    role.value,
                    role.value + "@example.test",
                    role.value,
                ),
            )
        )
        user = access_store.find_user("https://identity.example.test", role.value)
        token = security.random_token()
        access_store.create_session(
            security.digest(token), user.id, now, now + timedelta(hours=1)
        )
        tokens[role] = token
        users[role] = user
    store = PostgresqlPublicationStore(pool)
    access = AccessService(access_store, security, Clock())
    service = RefreshService(access, store, lambda: CONFIG, security)
    try:
        yield store, service, tokens, users, pool
    finally:
        pool.close()


def candidate(run, base=None):
    return PublishedGeneration(
        str(uuid4()),
        run.id,
        base,
        "manifest/verified.json",
        "a" * 64,
        "v1",
        datetime.now(UTC),
        tuple(
            DatasetSummary(grain, "v1", 10, INITIAL_START, INITIAL_END)
            for grain in AnalyticalGrain
        ),
    )


def expire(database):
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE refresh_coordination SET lease_until = clock_timestamp() - interval '1 second'"
        )


def test_authorize_before_reads_and_configuration(system, monkeypatch):
    store, service, tokens, users, pool = system

    def forbidden_lookup():
        pytest.fail("Denied read reached publication storage")

    monkeypatch.setattr(store, "latest", forbidden_lookup)
    for role in (Role.VIEWER, Role.ANALYST):
        with pytest.raises(ForbiddenError):
            service.latest(tokens[role])
        with pytest.raises(ForbiddenError):
            service.admit(tokens[role], "k" * 16, {})


def test_admission_freezes_interval_replays_before_config_and_rejects_overrides(system):
    store, service, tokens, users, pool = system
    assert service.latest(tokens[Role.ADMIN]) is None
    run = service.admit(tokens[Role.ADMIN], "k" * 16, {})
    assert run.status is RunStatus.ACCEPTED
    assert set(run.grains) == set(AnalyticalGrain)

    def invalid_configuration():
        raise ValueError("Changed invalid configuration")

    service._configuration = invalid_configuration
    assert service.admit(tokens[Role.ADMIN], "k" * 16, {}) == run
    assert service.status(tokens[Role.ADMIN], run.id).configuration == CONFIG
    assert service.latest(tokens[Role.ADMIN]).id == run.id
    with pytest.raises(InvalidRequestError):
        service.admit(tokens[Role.ADMIN], "k" * 16, {"start": "2026-10-01"})
    with pytest.raises(IdempotencyConflictError):
        store.replay(users[Role.ADMIN].id, run.key_digest, "different")


def test_scoped_idempotency_races_and_busy(system):
    store, service, tokens, users, pool = system
    with ThreadPoolExecutor(max_workers=4) as executor:
        runs = list(
            executor.map(
                lambda _: service.admit(tokens[Role.ADMIN], "r" * 16, {}), range(4)
            )
        )
    assert len({run.id for run in runs}) == 1
    with pytest.raises(RefreshBusyError):
        service.admit(tokens[Role.ADMIN], "s" * 16, {})


def test_initial_interval_and_all_grains(system):
    store, service, tokens, users, pool = system
    with pytest.raises(ValueError):
        store.admit(
            users[Role.ADMIN].id,
            "a" * 64,
            "refresh:v1:{}",
            replace(CONFIG, start=INITIAL_END),
        )
    assert store.latest() is None
    run = service.admit(tokens[Role.ADMIN], "g" * 16, {})
    owner = store.claim("worker", 60)
    with pytest.raises(ValueError):
        store.publish(
            owner, replace(candidate(run), datasets=candidate(run).datasets[:2])
        )
    assert store.active_generation() is None


def test_atomic_publication_history_and_prior_survives_failure(system):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "a" * 16, {})
    owner = store.claim("worker", 60)
    generation = candidate(run)
    succeeded = store.publish(
        owner,
        generation,
        '{"national":{"received_rows":4,"selected_rows":1,"excluded_rows":1,"duplicate_rows":1,"superseded_rows":1}}',
    )
    assert succeeded.status is RunStatus.SUCCEEDED
    assert store.active_generation() == generation
    second = service.admit(tokens[Role.ADMIN], "b" * 16, {})
    assert second.base_generation_id == generation.id
    assert store.active_generation() == generation
    second_owner = store.claim("worker", 60)
    store.finish(second_owner, RunStatus.FAILED, failure="retrieval")
    assert store.active_generation() == generation
    third = service.admit(tokens[Role.ADMIN], "c" * 16, {})
    store.publish(store.claim("worker", 60), candidate(third, generation.id))
    assert store.recover(run.id).generation_id == generation.id
    assert store.generation_for_run(run.id) == generation


def test_healthy_lease_recovery_expiration_and_stale_owner(system, database):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "l" * 16, {})
    owner = store.claim("worker", 60)
    assert store.claim("other", 60) is None
    assert store.recover(run.id).status is RunStatus.RUNNING
    store.heartbeat(owner, 60)
    store.progress(owner, RefreshStage.VERIFYING)
    expire(database)
    recovered = store.recover(run.id)
    assert recovered.status is RunStatus.INTERRUPTED
    assert store.claim("other", 60) is None
    for action in (
        lambda: store.publish(owner, candidate(run)),
        lambda: store.heartbeat(owner, 60),
        lambda: store.finish(owner, RunStatus.FAILED),
    ):
        with pytest.raises(StaleRefreshOwnerError):
            action()
    assert (
        service.admit(tokens[Role.ADMIN], "l" * 16, {}).status is RunStatus.INTERRUPTED
    )
    assert service.admit(tokens[Role.ADMIN], "m" * 16, {}).id != run.id


class FaultPool:
    def __init__(self, pool, mode):
        self.pool, self.mode, self.calls = pool, mode, 0

    @contextmanager
    def connection(self):
        self.calls += 1
        if self.calls > 1 and self.mode == "unavailable":
            raise AccessStoreError("Unavailable fresh connection")
        if self.calls == 1 and self.mode == "rollback":
            with self.pool.connection() as connection:
                yield connection
                raise AccessStoreError("Connection lost before commit")
        else:
            with self.pool.connection() as connection:
                yield connection
            if self.calls == 1:
                raise AccessStoreError("Commit response lost")


@pytest.mark.parametrize("mode", ["committed", "rollback", "unavailable"])
def test_commit_loss_uses_fresh_serialized_history(system, mode):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "f" * 16, {})
    owner = store.claim("worker", 60)
    faulty = PostgresqlPublicationStore(FaultPool(pool, mode))
    if mode == "unavailable":
        with pytest.raises(AccessStoreError):
            faulty.publish(owner, candidate(run))
        assert store.recover(run.id).status is RunStatus.SUCCEEDED
    else:
        result = faulty.publish(owner, candidate(run))
        assert result.status is (
            RunStatus.SUCCEEDED if mode == "committed" else RunStatus.INTERRUPTED
        )
        assert (store.generation_for_run(run.id) is not None) == (mode == "committed")


def test_no_runs_differs_from_unavailable(system):
    store, service, tokens, users, pool = system
    assert service.latest(tokens[Role.ADMIN]) is None
    pool.close()
    with pytest.raises(AccessStoreError):
        service.latest(tokens[Role.ADMIN])


def test_admission_and_publication_history_immutable(system, database):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "h" * 16, {})
    with psycopg.connect(database) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "UPDATE refresh_runs SET configuration = '{}' WHERE id = %s", (run.id,)
            )
    generation = candidate(run)
    store.publish(store.claim("worker", 60), generation)
    with psycopg.connect(database) as connection:
        with pytest.raises(psycopg.Error):
            connection.execute(
                "DELETE FROM published_generations WHERE id = %s", (generation.id,)
            )


def test_refresh_settings_validate_together():
    env = {
        "OUTAGE_REFRESH_START_DATE": "2026-04-02",
        "OUTAGE_REFRESH_END_DATE": "2026-10-01",
    }
    assert refresh_settings(env).start_date == CONFIG.start
    for overrides in (
        {"OUTAGE_REFRESH_MAX_INTERVAL_DAYS": "182"},
        {"OUTAGE_REFRESH_SOURCE_INTERVAL_DAYS": "1"},
        {"OUTAGE_REFRESH_CANDIDATE_SECONDS": "0"},
        {"OUTAGE_REFRESH_END_DATE": "2026-04-01"},
    ):
        with pytest.raises(ValueError):
            refresh_settings(env | overrides)


def test_compare_and_swap_rejects_wrong_base_and_duplicate_publication(system):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "p" * 16, {})
    owner = store.claim("worker", 60)
    with pytest.raises(StaleRefreshOwnerError):
        store.publish(owner, candidate(run, str(uuid4())))
    assert store.active_generation() is None
    generation = candidate(run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.publish, owner, generation) for _ in range(2)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except StaleRefreshOwnerError:
                results.append(None)
    assert len([result for result in results if result is not None]) == 1
    assert store.generation_for_run(run.id) == generation


def test_accepted_restart_and_revoked_admin_before_lookup(
    system, database, monkeypatch
):
    store, service, tokens, users, pool = system
    run = service.admit(tokens[Role.ADMIN], "q" * 16, {})
    restarted = PostgresqlPublicationStore(pool)
    assert restarted.recover(run.id).status is RunStatus.ACCEPTED
    assert restarted.claim("new-process", 60).run_id == run.id
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE users SET role_code = 'viewer' WHERE id = %s",
            (users[Role.ADMIN].id,),
        )
    monkeypatch.setattr(
        store, "latest", lambda: pytest.fail("Revoked admin reached lookup")
    )
    with pytest.raises(ForbiddenError):
        service.latest(tokens[Role.ADMIN])
