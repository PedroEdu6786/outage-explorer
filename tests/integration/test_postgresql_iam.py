"""Controlled IAM signing and physical pool connection attempts, never AWS."""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from psycopg.conninfo import conninfo_to_dict

from outage_explorer.application.errors import AccessStoreError
from outage_explorer.infrastructure.postgresql.credentials import (
    IAMCredentials,
    IAMTarget,
)
from outage_explorer.infrastructure.postgresql.pool import (
    BoundedPostgresqlPool,
    _AccessConnectionPool,
)

TARGET = IAMTarget("database.abc.us-east-1.rds.amazonaws.com", 5432, "app", "us-east-1")
DSN = "host=database.abc.us-east-1.rds.amazonaws.com dbname=outage user=app sslmode=verify-full"


def signing(target):
    return f"PRIVATE-TOKEN-{os.getpid()}-{time.time_ns()}"


def failing(target):
    raise RuntimeError("PRIVATE-TOKEN PRIVATE-CREDENTIAL")


def blocking(target):
    time.sleep(60)
    return "STALE-SECRET"


def test_fresh_bounded_signing_and_failure_sanitization(caplog, monkeypatch):
    monkeypatch.syspath_prepend(str(Path.cwd()))
    credentials = IAMCredentials(TARGET, signer=signing)
    first, second = credentials.token(), credentials.token()
    assert first != second
    assert "PRIVATE" not in repr(credentials) + caplog.text
    with pytest.raises(AccessStoreError, match="^PostgreSQL credentials unavailable$"):
        IAMCredentials(TARGET, signer=failing).token()
    started = time.monotonic()
    with pytest.raises(AccessStoreError, match="^PostgreSQL credentials unavailable$"):
        IAMCredentials(TARGET, signer=blocking, timeout_seconds=0.1).token()
    assert time.monotonic() - started < 2


def test_process_owned_credentials_and_pool():
    credentials = IAMCredentials(TARGET, signer=signing)
    pool = BoundedPostgresqlPool(DSN, password_provider=credentials.token)
    with patch("os.getpid", return_value=os.getpid() + 1):
        with pytest.raises(AccessStoreError, match="cross processes"):
            credentials.token()
        with pytest.raises(AccessStoreError, match="cross processes"):
            pool._connection_dsn()
    pool.close()


def test_each_physical_attempt_signs_after_15_minutes_and_on_retries(monkeypatch):
    signed = []

    def token():
        signed.append(len(signed))
        return f"TOKEN-{len(signed)}"

    pool = BoundedPostgresqlPool(DSN, password_provider=token)
    physical = pool._get_pool()
    observed = []

    def connect(dsn, **kwargs):
        observed.append(conninfo_to_dict(dsn)["password"])
        raise RuntimeError("PRIVATE driver error")

    monkeypatch.setattr("psycopg.Connection.connect", connect)
    for elapsed in (0, 901, 902):
        monkeypatch.setattr("time.monotonic", lambda elapsed=elapsed: elapsed)
        with pytest.raises(AccessStoreError, match="^PostgreSQL connection failed$"):
            physical._connect()
    assert observed == ["TOKEN-1", "TOKEN-2", "TOKEN-3"]
    assert "password" not in conninfo_to_dict(pool._dsn)
    pool.close()


def test_concurrent_tokens_do_not_mutate_shared_dsn():
    def token():
        return str(time.time_ns())

    pool = BoundedPostgresqlPool(DSN, password_provider=token)
    with ThreadPoolExecutor(max_workers=4) as executor:
        dsns = list(executor.map(lambda _: pool._connection_dsn(), range(8)))
    assert len({conninfo_to_dict(dsn)["password"] for dsn in dsns}) == 8
    assert pool._dsn == DSN
    pool.close()


def test_credential_failure_does_not_connect_or_use_password_fallback(monkeypatch):
    pool = BoundedPostgresqlPool(
        DSN, password_provider=lambda: (_ for _ in ()).throw(RuntimeError("SECRET"))
    )
    monkeypatch.setattr(
        "psycopg.Connection.connect", lambda *a, **k: pytest.fail("Connected")
    )
    with pytest.raises(AccessStoreError, match="connection failed"):
        pool._get_pool()._connect()
    pool.close()


def test_local_password_physical_failure_is_sanitized():
    pool = _AccessConnectionPool(
        "host=127.0.0.1 port=1 password=PRIVATE", min_size=0, max_size=1, open=False
    )
    with patch("psycopg.Connection.connect", side_effect=RuntimeError("PRIVATE")):
        with pytest.raises(AccessStoreError, match="^PostgreSQL connection failed$"):
            pool._connect()
    pool.close()


def test_forked_resources_reject_reuse_in_fresh_interpreter():
    import subprocess
    import sys

    script = """
import os
from outage_explorer.infrastructure.postgresql.credentials import IAMCredentials, IAMTarget
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.application.errors import AccessStoreError
credentials = IAMCredentials(IAMTarget("database.rds.amazonaws.com", 5432, "app", "us-east-1"))
pool = BoundedPostgresqlPool("host=127.0.0.1 dbname=unused", password_provider=credentials.token)
pid = os.fork()
if pid == 0:
    denied = 0
    for operation in (credentials.token, pool._get_pool, pool.close):
        try:
            operation()
        except AccessStoreError:
            denied += 1
    os._exit(0 if denied == 3 else 1)
_, status = os.waitpid(pid, 0)
pool.close()
assert status == 0
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0, result.stderr


def test_controlled_sdk_provider_uses_current_credentials_and_trusted_target(
    monkeypatch,
):
    from outage_explorer.infrastructure.postgresql.credentials import _aws_token

    calls, closed = [], []

    class Client:
        def generate_db_auth_token(self, **kwargs):
            calls.append(kwargs)
            return "TOKEN-" + str(len(calls))

        def close(self):
            closed.append(True)

    class Session:
        def __init__(self, **kwargs):
            assert kwargs == {
                "profile_name": TARGET.profile,
                "region_name": TARGET.region,
            }

        def client(self, name, *, config):
            assert name == "rds"
            assert config.connect_timeout == config.read_timeout == 1
            assert config.retries == {"total_max_attempts": 1}
            return Client()

    monkeypatch.setattr("boto3.Session", Session)
    assert _aws_token(TARGET) == "TOKEN-1"
    assert _aws_token(TARGET) == "TOKEN-2"
    assert (
        calls
        == [
            {
                "DBHostname": TARGET.host,
                "Port": TARGET.port,
                "DBUsername": TARGET.user,
                "Region": TARGET.region,
            }
        ]
        * 2
    )
    assert closed == [True, True]
