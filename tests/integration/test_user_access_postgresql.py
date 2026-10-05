"""Real PostgreSQL constraints and short-transaction semantics; local only."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from outage_explorer.application.dto import SeedIdentity
from outage_explorer.application.errors import (
    AccessConfigurationError,
    AccessStoreError,
    LoginAttemptLimitError,
    SeedConflictError,
)
from outage_explorer.application.services.seed_users import SeedUsers
from outage_explorer.domain.access import LoginAttempt, Role
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.migrations import run_migrations
from outage_explorer.infrastructure.postgresql.pool import (
    BoundedPostgresqlPool,
    validate_dsn,
)

NOW = datetime(2026, 10, 4, tzinfo=UTC)
PERSONAS = tuple(
    SeedIdentity(
        "https://identity.example.test/pool",
        role.value,
        f"{role.value}@example.test",
        role.value,
    )
    for role in Role
)


@pytest.fixture
def database():
    admin = os.environ.get("OUTAGE_TEST_POSTGRES_DSN")
    if not admin:
        pytest.fail(
            "Required database missing: set OUTAGE_TEST_POSTGRES_DSN to an explicit local disposable database"
        )
    values = conninfo_to_dict(admin)
    if (
        values.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or "hostaddr" in values
    ):
        pytest.fail("Integration tests require explicit loopback PostgreSQL")
    name = "access_test_" + uuid4().hex
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
def store(database):
    pool = BoundedPostgresqlPool(database)
    try:
        yield PostgresqlAccessStore(pool)
    finally:
        pool.close()


def attempt(state="a", created=NOW):
    return LoginAttempt(
        state * 64,
        "b" * 64,
        "v" * 43,
        "https://backend.example.test/api/auth/callback",
        "/",
        created,
        created + timedelta(minutes=10),
    )


def test_personas_idempotent_role_sharing_and_essential_schema(database, store):
    assert SeedUsers(store).execute(PERSONAS) == 3
    before = [
        store.find_user(item.identity_issuer, item.identity_subject)
        for item in PERSONAS
    ]
    assert [user.role for user in before] == list(Role)
    assert SeedUsers(store).execute(PERSONAS) == 0
    assert before == [
        store.find_user(item.identity_issuer, item.identity_subject)
        for item in PERSONAS
    ]
    extra = replace(
        PERSONAS[0], identity_subject="another-viewer", email="another@example.test"
    )
    assert store.seed((extra,)) == 1
    assert (
        store.find_user(extra.identity_issuer, extra.identity_subject).role
        == Role.VIEWER
    )
    with psycopg.connect(database) as connection:
        fields = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='users'"
        ).fetchall()
        assert {row[0] for row in fields} == {
            "id",
            "identity_issuer",
            "identity_subject",
            "email",
            "role_code",
        }
        assert connection.execute(
            "SELECT code FROM roles ORDER BY code"
        ).fetchall() == [("admin",), ("analyst",), ("viewer",)]


@pytest.mark.parametrize(
    "change",
    [
        {"role": "admin"},
        {"email": "new@example.test"},
        {"identity_subject": "new-subject"},
    ],
)
def test_seed_conflict_rolls_back_every_addition(store, change):
    store.seed(PERSONAS)
    fresh = replace(PERSONAS[0], identity_subject="fresh", email="fresh@example.test")
    with pytest.raises(SeedConflictError):
        store.seed((fresh, replace(PERSONAS[0], **change)))
    assert store.find_user(fresh.identity_issuer, fresh.identity_subject) is None
    assert store.find_user(PERSONAS[0].identity_issuer, "viewer").role == Role.VIEWER


@pytest.mark.parametrize(
    "records",
    [
        (),
        (PERSONAS[0], PERSONAS[0]),
        (replace(PERSONAS[0], identity_subject=""),),
        (replace(PERSONAS[0], role="owner"),),
    ],
)
def test_invalid_manifest_no_seed(store, records):
    with pytest.raises((AccessConfigurationError, SeedConflictError)):
        SeedUsers(store).execute(records)
    assert store.find_user(PERSONAS[0].identity_issuer, "viewer") is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("role_code", None),
        ("role_code", "owner"),
        ("identity_subject", ""),
        ("identity_issuer", " "),
        ("email", ""),
    ],
)
def test_database_rejects_invalid_single_role_and_linkage(
    database, store, field, value
):
    store.seed(PERSONAS)
    with psycopg.connect(database) as connection, pytest.raises(psycopg.IntegrityError):
        connection.execute(
            sql.SQL("UPDATE users SET {}=%s WHERE identity_subject='viewer'").format(
                sql.Identifier(field)
            ),
            (value,),
        )


def test_duplicate_subject_rejected_by_database(database, store):
    store.seed(PERSONAS)
    with psycopg.connect(database) as connection, pytest.raises(psycopg.IntegrityError):
        connection.execute(
            "INSERT INTO users SELECT %s,identity_issuer,identity_subject,email,role_code FROM users LIMIT 1",
            (uuid4(),),
        )


def test_fixed_expiry_current_role_and_current_session_logout(database, store):
    store.seed(PERSONAS)
    user = store.find_user(PERSONAS[0].identity_issuer, "viewer")
    expiry = NOW + timedelta(hours=1)
    store.create_session("a" * 64, user.id, NOW, expiry)
    store.create_session("b" * 64, user.id, NOW, expiry)
    assert store.resolve_session("a" * 64, NOW - timedelta(seconds=1)) is None
    assert (
        store.resolve_session("a" * 64, expiry - timedelta(microseconds=1)).expires_at
        == expiry
    )
    assert store.resolve_session("a" * 64, expiry) is None
    with psycopg.connect(database) as connection:
        connection.execute("UPDATE users SET role_code='admin' WHERE id=%s", (user.id,))
    assert store.resolve_session("a" * 64, NOW).user.role == Role.ADMIN
    store.revoke_session("a" * 64, NOW)
    store.revoke_session("a" * 64, NOW)
    assert store.resolve_session("a" * 64, NOW) is None
    assert store.resolve_session("b" * 64, NOW) is not None
    with psycopg.connect(database) as connection, pytest.raises(psycopg.Error):
        connection.execute(
            "UPDATE application_sessions SET expires_at=expires_at+interval '1 second'"
        )
    assert store.cleanup(expiry) == (2, 0)


def test_sessions_reject_raw_tokens_and_invalid_expiry(store):
    store.seed(PERSONAS)
    user = store.find_user(PERSONAS[0].identity_issuer, "viewer")
    with pytest.raises(AccessStoreError):
        store.create_session("raw-token", user.id, NOW, NOW + timedelta(hours=1))
    with pytest.raises(AccessStoreError):
        store.create_session("a" * 64, user.id, NOW, NOW)


def test_attempts_binding_replay_expiry_admission_and_cleanup(database):
    pool = BoundedPostgresqlPool(database)
    try:
        store = PostgresqlAccessStore(pool, attempt_limit=1)
        request = attempt()
        store.create_attempt(request, NOW)
        with pytest.raises(LoginAttemptLimitError):
            store.create_attempt(attempt("c"), NOW)
        assert store.consume_attempt(request.state_digest, "c" * 64, NOW) is None
        assert (
            store.consume_attempt(
                request.state_digest, request.browser_binding_digest, NOW
            )
            == request
        )
        assert (
            store.consume_attempt(
                request.state_digest, request.browser_binding_digest, NOW
            )
            is None
        )
        store.create_attempt(request, NOW)
        assert (
            store.consume_attempt(
                request.state_digest, request.browser_binding_digest, request.expires_at
            )
            is None
        )
        assert store.cleanup(request.expires_at) == (0, 1)
        store.create_attempt(attempt("c", request.expires_at), request.expires_at)
    finally:
        pool.close()


def test_attempt_consumption_is_atomic_under_concurrency(store):
    request = attempt()
    store.create_attempt(request, NOW)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: store.consume_attempt(
                    request.state_digest, request.browser_binding_digest, NOW
                ),
                range(4),
            )
        )
    assert results.count(request) == 1
    assert results.count(None) == 3


def test_admission_is_serialized_under_concurrency(database):
    pool = BoundedPostgresqlPool(database)
    try:
        store = PostgresqlAccessStore(pool, attempt_limit=1)

        def create(state):
            try:
                store.create_attempt(attempt(state), NOW)
                return True
            except LoginAttemptLimitError:
                return False

        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(create, "acde")) == 1
    finally:
        pool.close()


def test_pool_is_lazy_closed_and_process_owned(database, monkeypatch):
    pool = BoundedPostgresqlPool(database)
    assert pool._pool is None
    monkeypatch.setattr(
        "outage_explorer.infrastructure.postgresql.pool.os.getpid", lambda: -1
    )
    with pytest.raises(AccessStoreError):
        with pool.connection():
            pass
    monkeypatch.undo()
    pool.close()
    with pytest.raises(AccessStoreError):
        with pool.connection():
            pass


@pytest.mark.parametrize(
    "dsn",
    [
        "",
        "host=db.example.test dbname=test",
        "host=127.0.0.1 hostaddr=192.0.2.1",
        "service=secret",
        "host=127.0.0.1,remote",
    ],
)
def test_dsn_rejects_insecure_or_implicit_targets(dsn):
    with pytest.raises(AccessConfigurationError):
        validate_dsn(dsn)


def test_remote_configuration_requires_certificate_verification():
    assert validate_dsn("host=db.example.test sslmode=verify-full")


def test_migrations_are_repeatable(database, store):
    store.seed(PERSONAS)
    run_migrations(database)
    assert store.find_user(PERSONAS[0].identity_issuer, "viewer") is not None


class FixedClock:
    def now(self):
        return NOW


class BoundProvider:
    def __init__(self):
        self.calls = 0

    def authorization_url(self, callback, state, challenge):
        return "https://provider.test/?state=" + state

    def exchange(self, code, verifier, callback):
        from outage_explorer.application.dto import VerifiedIdentity

        self.calls += 1
        return VerifiedIdentity(
            PERSONAS[0].identity_issuer, PERSONAS[0].identity_subject
        )


def test_real_service_sessions_committed_logout_and_concurrent_replay(store, database):
    from urllib.parse import parse_qs, urlsplit

    from outage_explorer.application.errors import UnauthenticatedError
    from outage_explorer.application.services.access import AccessService
    from outage_explorer.application.services.login import LoginService
    from outage_explorer.infrastructure.security import RandomSecurityMaterial

    store.seed(PERSONAS)
    security, clock, provider = RandomSecurityMaterial(), FixedClock(), BoundProvider()
    login = LoginService(
        provider,
        store,
        store,
        store,
        security,
        clock,
        callback_uri="https://backend.test/callback",
    )
    access = AccessService(store, security, clock)

    def sign_in():
        redirect = login.begin()
        state = parse_qs(urlsplit(redirect.authorization_url).query)["state"][0]
        session = login.complete("code", state, redirect.browser_binding)
        with pytest.raises(UnauthenticatedError):
            login.complete("code", state, redirect.browser_binding)
        return session

    first, second = sign_in(), sign_in()
    assert provider.calls == 2
    assert first.expires_at == second.expires_at == NOW + timedelta(hours=1)
    for _ in range(3):
        assert access.current_identity(first.token).expires_at == first.expires_at
    access.logout(first.token)
    # Separate connections after the returned success observe committed invalidation.
    with psycopg.connect(database) as connection:
        row = connection.execute(
            "SELECT revoked_at FROM application_sessions WHERE token_digest=%s",
            (security.digest(first.token),),
        ).fetchone()
        assert row[0] == NOW

    def check(_):
        with pytest.raises(UnauthenticatedError):
            access.resolve(first.token)
        return access.resolve(second.token).expires_at

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert list(executor.map(check, range(8))) == [second.expires_at] * 8
    access.logout(first.token)
    assert access.resolve(second.token)


def test_failed_database_commit_is_not_logout_success(store, database):
    from outage_explorer.application.services.access import AccessService
    from outage_explorer.infrastructure.security import RandomSecurityMaterial

    store.seed(PERSONAS)
    user = store.find_user(PERSONAS[0].identity_issuer, PERSONAS[0].identity_subject)
    security = RandomSecurityMaterial()
    token = security.random_token()
    store.create_session(security.digest(token), user.id, NOW, NOW + timedelta(hours=1))
    access = AccessService(store, security, FixedClock())
    # Raise during COMMIT, after UPDATE itself succeeded, to verify rollback handling.
    with psycopg.connect(database) as connection:
        connection.execute(
            "CREATE FUNCTION fail_logout_commit() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'controlled commit failure'; END $$"
        )
        connection.execute(
            "CREATE CONSTRAINT TRIGGER fail_logout AFTER UPDATE ON application_sessions DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fail_logout_commit()"
        )
    with pytest.raises(AccessStoreError):
        access.logout(token)
    assert access.resolve(token).expires_at == NOW + timedelta(hours=1)
    with psycopg.connect(database) as connection:
        connection.execute("DROP TRIGGER fail_logout ON application_sessions")
    access.logout(token)
    assert store.resolve_session(security.digest(token), NOW) is None


def test_session_service_database_unavailable_fails_closed(database):
    from outage_explorer.application.services.access import AccessService
    from outage_explorer.infrastructure.security import RandomSecurityMaterial

    pool = BoundedPostgresqlPool(database)
    pool.close()
    security = RandomSecurityMaterial()
    access = AccessService(PostgresqlAccessStore(pool), security, FixedClock())
    token = security.random_token()
    with pytest.raises(AccessStoreError):
        access.resolve(token)
    with pytest.raises(AccessStoreError):
        access.logout(token)
