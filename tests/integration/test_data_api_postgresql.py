"""Disposable PostgreSQL races, publication fencing and commit-loss evidence."""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import (
    AccessStoreError,
    ForbiddenError,
    InvalidRequestError,
    RefreshBusyError,
    StaleRefreshOwnerError,
    UnsupportedPublicationLayoutError,
)
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.refresh import RefreshService
from outage_explorer.domain.access import AnalyticalGrain, Role
from outage_explorer.domain.publication import (
    INITIAL_END,
    INITIAL_START,
    DatasetSummary,
    RefreshConfiguration,
    RefreshStage,
    ResourcePublishedGeneration,
    RunStatus,
)
from outage_explorer.infrastructure.postgresql import migrations
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.migrations import run_migrations
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlResourcePublicationStore,
)
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.settings import refresh_settings

CONFIG = RefreshConfiguration(INITIAL_START, INITIAL_END, 183, 183, 183, 1800, 1800)


@contextmanager
def disposable_database(*, migrated):
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
        if migrated:
            run_migrations(dsn)
        yield dsn
    finally:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def database():
    with disposable_database(migrated=True) as dsn:
        yield dsn


@pytest.fixture
def empty_database():
    with disposable_database(migrated=False) as dsn:
        yield dsn


def migrate(dsn, action, revision):
    """Controlled revision movement on a disposable database only."""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool

    raw = psycopg.connect(dsn)
    engine = create_engine(
        "postgresql+psycopg://", creator=lambda: raw, poolclass=NullPool
    )
    try:
        with engine.begin() as connection:
            config = Config(str(Path(migrations.__file__).with_name("alembic.ini")))
            config.attributes["connection"] = connection
            getattr(command, action)(config, revision)
    finally:
        engine.dispose()
        raw.close()


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
    store = PostgresqlResourcePublicationStore(pool)
    access = AccessService(access_store, security, Clock())
    service = RefreshService(access, store, lambda: CONFIG, security)
    try:
        yield store, service, tokens, users, pool
    finally:
        pool.close()


def candidate(run, base=None):
    return resource_candidate(run, base)


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
    assert store.replay(users[Role.ADMIN].id, run.key_digest) == run
    assert store.replay(users[Role.ANALYST].id, run.key_digest) is None


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
    faulty = PostgresqlResourcePublicationStore(FaultPool(pool, mode))
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
    }
    assert refresh_settings(env).start_date == CONFIG.start
    for overrides in (
        {"OUTAGE_REFRESH_CANDIDATE_SECONDS": "0"},
        {"OUTAGE_REFRESH_PERSISTENCE_SECONDS": "0"},
        {"OUTAGE_REFRESH_S3_WORKERS": "4"},
        {"OUTAGE_REFRESH_START_DATE": "2026-02-30"},
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
    restarted = PostgresqlResourcePublicationStore(pool)
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


FILES = {
    AnalyticalGrain.NATIONAL: "national",
    AnalyticalGrain.FACILITY: "facilities",
    AnalyticalGrain.GENERATOR: "generators",
}


def resource_candidate(run, base=None):
    identity = str(uuid4())
    return ResourcePublishedGeneration(
        identity,
        run.id,
        base,
        "v1",
        datetime.now(UTC),
        tuple(
            DatasetSummary(
                grain,
                "v1",
                10 + index,
                INITIAL_START,
                INITIAL_END,
                f"connector/generations/{identity}/{FILES[grain]}.parquet",
                f"{index + 1:x}" * 64,
                1000 + index,
            )
            for index, grain in enumerate(AnalyticalGrain)
        ),
    )


@pytest.fixture
def resources(system):
    store, service, tokens, users, pool = system
    resource_store = PostgresqlResourcePublicationStore(pool)
    resource_service = RefreshService(
        service._access, resource_store, lambda: CONFIG, service._security
    )
    return resource_store, resource_service, tokens, pool


def test_resource_publication_is_atomic_exact_and_manifest_free(resources, database):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "r1" * 8, {})
    owner = store.claim("worker", 60)
    generation = resource_candidate(run)
    quality = '{"national":{"received_rows":4,"selected_rows":1,"excluded_rows":1,"duplicate_rows":1,"superseded_rows":1}}'
    result = store.publish(owner, generation, quality)
    assert result.status is RunStatus.SUCCEEDED
    assert result.generation_id == generation.id
    assert json.loads(result.quality_json) == json.loads(quality)
    assert store.active_generation() == generation
    assert store.generation_for_run(run.id) == generation
    assert [item.object_key for item in generation.datasets] == [
        item.object_key for item in store.active_generation().datasets
    ]
    with psycopg.connect(database) as connection:
        manifest = connection.execute(
            "SELECT jsonb_array_length(datasets) FROM published_generations WHERE id = %s",
            (generation.id,),
        ).fetchone()
        pointer = connection.execute(
            "SELECT active_generation_id::text, active_run_id FROM refresh_coordination"
        ).fetchone()
    assert manifest == (3,)
    assert pointer == (generation.id, None)
    # Subsequent publications retain immutable prior history and the base chain.
    second = service.admit(tokens[Role.ADMIN], "r2" * 8, {})
    assert second.base_generation_id == generation.id
    store.publish(store.claim("worker", 60), resource_candidate(second, generation.id))
    assert store.generation_for_run(run.id) == generation
    assert store.active_generation().base_generation_id == generation.id


def test_resource_publication_fences_and_failure_preserve_prior_state(resources):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "f1" * 8, {})
    owner = store.claim("worker", 60)
    with pytest.raises(StaleRefreshOwnerError):
        store.publish(owner, resource_candidate(run, str(uuid4())))
    other = resource_candidate(run)
    with pytest.raises(ValueError):
        store.publish(owner, replace(other, run_id=str(uuid4())))
    with pytest.raises(ValueError):
        store.publish(owner, replace(other, datasets=other.datasets[:2]))
    assert store.active_generation() is None
    generation = resource_candidate(run)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(store.publish, owner, generation) for _ in range(2)]
        results = []
        for future in futures:
            try:
                results.append(future.result())
            except StaleRefreshOwnerError:
                results.append(None)
    assert len([result for result in results if result is not None]) == 1
    second = service.admit(tokens[Role.ADMIN], "f2" * 8, {})
    failed = store.claim("worker", 60)
    store.finish(failed, RunStatus.FAILED, failure="retrieval")
    assert store.active_generation() == generation
    assert store.generation_for_run(second.id) is None
    with pytest.raises(StaleRefreshOwnerError):
        store.publish(failed, resource_candidate(second, generation.id))
    assert store.active_generation() == generation


def test_resource_stale_owner_after_lease_expiry(resources, database):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "e1" * 8, {})
    owner = store.claim("worker", 60)
    expire(database)
    with pytest.raises(StaleRefreshOwnerError):
        store.publish(owner, resource_candidate(run))
    assert store.active_generation() is None
    assert store.recover(run.id).status is RunStatus.INTERRUPTED


@pytest.mark.parametrize("mode", ["committed", "rollback", "unavailable"])
def test_resource_commit_loss_uses_fresh_serialized_history(resources, mode):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "c1" * 8, {})
    owner = store.claim("worker", 60)
    faulty = PostgresqlResourcePublicationStore(FaultPool(pool, mode))
    if mode == "unavailable":
        with pytest.raises(AccessStoreError):
            faulty.publish(owner, resource_candidate(run))
        assert store.recover(run.id).status is RunStatus.SUCCEEDED
    else:
        result = faulty.publish(owner, resource_candidate(run))
        assert result.status is (
            RunStatus.SUCCEEDED if mode == "committed" else RunStatus.INTERRUPTED
        )
        assert (store.generation_for_run(run.id) is not None) == (mode == "committed")
        assert (store.active_generation() is not None) == (mode == "committed")


def test_resource_history_is_immutable(resources, database):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "h1" * 8, {})
    generation = resource_candidate(run)
    store.publish(store.claim("worker", 60), generation)
    with psycopg.connect(database) as connection:
        for statement in (
            "UPDATE published_generations SET datasets = '[]' WHERE id = %s",
            "DELETE FROM published_generations WHERE id = %s",
        ):
            with pytest.raises(psycopg.Error):
                connection.execute(statement, (generation.id,))
            connection.rollback()


def _datasets(generation):
    return [
        {
            "grain": item.grain.value,
            "schema_version": "v1",
            "rows": item.rows,
            "start": item.start.isoformat(),
            "end": item.end.isoformat(),
            "object_key": item.object_key,
            "sha256": item.sha256,
            "byte_count": item.byte_count,
        }
        for item in generation.datasets
    ]


def _insert(database, run_id, generation, datasets):
    with psycopg.connect(database) as connection:
        connection.execute(
            "INSERT INTO published_generations(id, run_id, verification_version, verified_at, datasets) VALUES (%s,%s,'v1',now(),%s)",
            (
                generation.id,
                run_id,
                psycopg.types.json.Jsonb(datasets),
            ),
        )


def _mutations():
    def at(index, **changes):
        def apply(datasets):
            datasets[index].update(changes)

        return apply

    def drop(name):
        def apply(datasets):
            del datasets[0][name]

        return apply

    return {
        "wrong-count": lambda datasets: datasets.pop(),
        "duplicate-grain": lambda datasets: datasets[1].update(
            grain=datasets[0]["grain"]
        ),
        "duplicate-key": lambda datasets: datasets[1].update(
            object_key=datasets[0]["object_key"]
        ),
        "unknown-grain": at(0, grain="region"),
        "missing-key": drop("object_key"),
        "missing-sha": drop("sha256"),
        "missing-bytes": drop("byte_count"),
        "upper-sha": at(0, sha256="A" * 64),
        "short-sha": at(0, sha256="a" * 63),
        "zero-bytes": at(0, byte_count=0),
        "string-bytes": at(0, byte_count="12"),
        "fractional-bytes": at(0, byte_count=1.5),
        "zero-rows": at(0, rows=0),
        "bad-schema": at(0, schema_version="v2"),
        "traversal": at(0, object_key="a/../national.parquet"),
        "absolute": at(0, object_key="/generations/x/national.parquet"),
        "backslash": at(0, object_key="a\\national.parquet"),
        "other-generation": at(
            0,
            object_key="connector/generations/" + str(uuid4()) + "/national.parquet",
        ),
        "wrong-file": at(0, object_key="WRONG-FILE"),
        "reversed-dates": at(0, start="2026-10-02", end="2026-10-01"),
        "bad-date": at(0, start="not-a-date"),
        "not-array": None,
    }


@pytest.mark.parametrize("name", list(_mutations()))
def test_database_rejects_malformed_resource_descriptors(resources, database, name):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "d1" * 8, {})
    generation = resource_candidate(run)
    datasets = _datasets(generation)
    mutate = _mutations()[name]
    if mutate is None:
        datasets = {"grain": "national"}
    else:
        key = datasets[0]["object_key"]
        mutate(datasets)
        if datasets[0].get("object_key") == "WRONG-FILE":
            datasets[0]["object_key"] = key.replace("national", "facilities")
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(database, run.id, generation, datasets)
    assert store.active_generation() is None


def test_database_rejects_summaries_without_exact_descriptors(resources, database):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "m1" * 8, {})
    generation = resource_candidate(run)
    summaries = [
        {
            k: v
            for k, v in item.items()
            if k not in {"object_key", "sha256", "byte_count"}
        }
        for item in _datasets(generation)
    ]
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert(database, run.id, generation, summaries)
    assert store.active_generation() is None


def _old_history(dsn, *, resource=False):
    """Create publication history as stored before column removal."""
    pool = BoundedPostgresqlPool(dsn)
    try:
        PostgresqlAccessStore(pool).seed(
            (
                SeedIdentity(
                    "https://identity.example.test", "a", "a@example.test", "admin"
                ),
            )
        )
    finally:
        pool.close()
    run_id, generation_id = str(uuid4()), str(uuid4())
    datasets = [
        {
            "grain": grain.value,
            "schema_version": "v1",
            "rows": 5,
            "start": "2026-04-02",
            "end": "2026-10-01",
        }
        for grain in AnalyticalGrain
    ]
    if resource:
        for item in datasets:
            item.update(
                object_key=f"connector/generations/{generation_id}/{FILES[AnalyticalGrain(item['grain'])]}.parquet",
                sha256="a" * 64,
                byte_count=1000,
            )
    with psycopg.connect(dsn) as connection:
        requester = connection.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
        connection.execute(
            "INSERT INTO refresh_runs(id, requester_id, key_digest, request_identity, configuration, status, stage, publication) VALUES (%s,%s,%s,'r','{}','accepted','queued','pending')",
            (run_id, requester, "a" * 64),
        )
        connection.execute(
            "INSERT INTO published_generations(id, run_id, manifest_key, manifest_digest, verification_version, verified_at, datasets) VALUES (%s,%s,%s,%s,'v1',now(),%s)",
            (
                generation_id,
                run_id,
                None if resource else "m",
                None if resource else "b" * 64,
                psycopg.types.json.Jsonb(datasets),
            ),
        )
        connection.execute(
            "UPDATE refresh_runs SET status='succeeded', publication='published', generation_id=%s, stage='finished' WHERE id=%s",
            (generation_id, run_id),
        )
        connection.execute(
            "UPDATE refresh_coordination SET active_generation_id = %s",
            (generation_id,),
        )
    return run_id, generation_id


def _state(dsn):
    with psycopg.connect(dsn) as connection:
        return [
            connection.execute(query).fetchall()
            for query in (
                "SELECT id, run_id, base_generation_id, verification_version, verified_at, datasets FROM published_generations ORDER BY id",
                "SELECT to_jsonb(r) - 'operation' - 'request_identity' - 'updated_at' FROM refresh_runs r ORDER BY id",
                "SELECT * FROM refresh_coordination",
            )
        ]


def test_remove_columns_preserves_history_pointer_and_guards(empty_database):
    migrate(empty_database, "upgrade", "0003_refresh_timestamps")
    run_id, generation_id = _old_history(empty_database)
    before = _state(empty_database)
    migrate(empty_database, "upgrade", "head")
    assert _state(empty_database) == before
    with psycopg.connect(empty_database) as connection:
        for statement in (
            "UPDATE published_generations SET datasets = '[]'",
            "DELETE FROM published_generations",
            "UPDATE refresh_runs SET key_digest = repeat('x',64)",
        ):
            with pytest.raises(psycopg.Error):
                connection.execute(statement)
            connection.rollback()
        assert connection.execute(
            "SELECT count(*) FROM pg_trigger WHERE tgname IN ('publication_history','refresh_snapshot')"
        ).fetchone() == (2,)
    pool = BoundedPostgresqlPool(empty_database)
    try:
        store = PostgresqlResourcePublicationStore(pool)
        with pytest.raises(UnsupportedPublicationLayoutError):
            store.active_generation()
        with pytest.raises(UnsupportedPublicationLayoutError):
            store.generation_for_run(run_id)
        with psycopg.connect(empty_database) as connection:
            requester = str(
                connection.execute("SELECT id FROM users LIMIT 1").fetchone()[0]
            )
        with pytest.raises(UnsupportedPublicationLayoutError):
            store.admit(requester, "z" * 64, CONFIG)
        assert _state(empty_database) == before
    finally:
        pool.close()
    _assert_no_manifest_columns(empty_database)


def _assert_no_manifest_columns(dsn):
    with psycopg.connect(dsn) as connection:
        assert (
            connection.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'published_generations' AND column_name IN ('manifest_key', 'manifest_digest')"
            ).fetchall()
            == []
        )


def test_remove_columns_preserves_resource_publication(empty_database):
    migrate(empty_database, "upgrade", "0004_refresh_resource_files")
    run_id, identity = _old_history(empty_database, resource=True)
    before = _state(empty_database)
    pool = BoundedPostgresqlPool(empty_database)
    try:
        store = PostgresqlResourcePublicationStore(pool)
        generation = store.active_generation()
        assert generation.id == identity
        migrate(empty_database, "upgrade", "head")
        assert _state(empty_database) == before
        _assert_no_manifest_columns(empty_database)
        assert store.active_generation() == generation
        assert store.generation_for_run(run_id) == generation
    finally:
        pool.close()


def test_removed_manifest_values_cannot_be_recreated_by_downgrade(resources, database):
    store, service, tokens, pool = resources
    run = service.admit(tokens[Role.ADMIN], "dg1" * 6, {})
    store.publish(store.claim("worker", 60), resource_candidate(run))
    before = _state(database)
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        migrate(database, "downgrade", "0004_refresh_resource_files")
    assert _state(database) == before
    _assert_no_manifest_columns(database)
    with psycopg.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0006_simplify_refresh_runs",)


def test_refresh_cleanup_preserves_admitted_retry_and_fenced_publication(
    empty_database,
):
    migrate(empty_database, "upgrade", "0005_remove_manifest_columns")
    with contextmanager(system.__wrapped__)(empty_database) as state:
        store, service, tokens, users, pool = state
        run_id = str(uuid4())
        key = "migration-key-001"
        digest = service._security.digest(key)
        configuration = asdict(CONFIG) | {
            "start": CONFIG.start.isoformat(),
            "end": CONFIG.end.isoformat(),
        }
        with psycopg.connect(empty_database) as connection:
            connection.execute(
                "INSERT INTO refresh_runs(id, requester_id, key_digest, request_identity, configuration, status, stage, publication) VALUES (%s,%s,%s,'refresh:v1:{}',%s,'accepted','queued','pending')",
                (
                    run_id,
                    users[Role.ADMIN].id,
                    digest,
                    psycopg.types.json.Jsonb(configuration),
                ),
            )
            connection.execute(
                "UPDATE refresh_coordination SET active_run_id=%s", (run_id,)
            )
        before = _state(empty_database)
        migrate(empty_database, "upgrade", "head")
        assert _state(empty_database) == before
        with psycopg.connect(empty_database) as connection:
            assert (
                connection.execute(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='refresh_runs' AND column_name IN ('operation','request_identity','updated_at')"
                ).fetchall()
                == []
            )

        def changed_configuration():
            pytest.fail("Replay must not resolve changed configuration")

        service._configuration = changed_configuration
        run = service.admit(tokens[Role.ADMIN], key, {})
        assert run.id == run_id
        assert run.configuration == CONFIG
        assert store.replay(users[Role.ANALYST].id, digest) is None
        owner = store.claim("worker", 60)
        store.progress(owner, RefreshStage.PUBLISHING)
        generation = resource_candidate(run)
        assert store.publish(owner, generation).status is RunStatus.SUCCEEDED
        assert store.active_generation() == generation
        assert service.admit(tokens[Role.ADMIN], key, {}).generation_id == generation.id
        with psycopg.connect(empty_database) as connection:
            with pytest.raises(psycopg.errors.UniqueViolation):
                connection.execute(
                    "INSERT INTO refresh_runs(id, requester_id, key_digest, configuration, status, stage, publication) VALUES (%s,%s,%s,%s,'accepted','queued','pending')",
                    (
                        str(uuid4()),
                        users[Role.ADMIN].id,
                        digest,
                        psycopg.types.json.Jsonb(configuration),
                    ),
                )
            connection.rollback()
            for field, value in (
                ("requester_id", str(users[Role.ANALYST].id)),
                ("key_digest", "e" * 64),
                ("configuration", "{}"),
                ("base_generation_id", generation.id),
            ):
                with pytest.raises(
                    psycopg.Error, match="Refresh admission is immutable"
                ):
                    connection.execute(
                        sql.SQL("UPDATE refresh_runs SET {}=%s WHERE id=%s").format(
                            sql.Identifier(field)
                        ),
                        (value, run_id),
                    )
                connection.rollback()
            with pytest.raises(
                psycopg.Error, match="Durable publication history is immutable"
            ):
                connection.execute("DELETE FROM refresh_runs WHERE id=%s", (run_id,))
            connection.rollback()
