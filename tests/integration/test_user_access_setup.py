"""Explicit CLI setup remains independent of AWS and connector execution."""

import json
import subprocess
import sys
from dataclasses import asdict

import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from outage_explorer.application.dto import AccessSetupInput
from outage_explorer.application.errors import (
    AccessConfigurationError,
    AccessStoreError,
)
from outage_explorer.bootstrap import execute_access_setup
from outage_explorer.entrypoints.cli.access_setup import read_manifest, run
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool

from . import test_user_access_postgresql as pg_tests
from .test_user_access_postgresql import PERSONAS

database = pg_tests.database


def test_setup_seed_rerun_and_cleanup(database, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv("OUTAGE_ACCESS_DATABASE_DSN", database)
    path = tmp_path / "personas.json"
    path.write_text(json.dumps([asdict(item) for item in PERSONAS]))
    assert run(execute_access_setup, ["seed", "--manifest", str(path)]) == 0
    assert run(execute_access_setup, ["seed", "--manifest", str(path)]) == 0
    assert run(execute_access_setup, ["migrate"]) == 0
    assert run(execute_access_setup, ["cleanup"]) == 0
    pool = BoundedPostgresqlPool(database)
    try:
        store = PostgresqlAccessStore(pool)
        assert all(
            store.find_user(item.identity_issuer, item.identity_subject)
            for item in PERSONAS
        )
    finally:
        pool.close()


def test_help_has_no_setup_io(capsys):
    def forbidden(inputs):
        pytest.fail("Help must not call setup composition")

    with pytest.raises(SystemExit) as result:
        run(forbidden, ["--help"])
    assert result.value.code == 0
    assert "cleanup" in capsys.readouterr().out


def test_import_and_executable_help_have_no_network_or_database_io():
    code = """
import socket, psycopg, psycopg_pool
from unittest.mock import patch
with patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(psycopg, "connect", side_effect=AssertionError("database")), patch.object(psycopg_pool.ConnectionPool, "open", side_effect=AssertionError("pool")):
    from outage_explorer.entrypoints.cli.access_startup import main
    import sys
    sys.argv = ["access-setup", "--help"]
    main()
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert "cleanup" in result.stdout


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        [{"password": "excluded"}],
        [{**asdict(PERSONAS[0]), "role": ["viewer", "admin"]}],
    ],
)
def test_manifest_rejects_credentials_or_multiple_roles(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(AccessConfigurationError):
        read_manifest(str(path))


def test_setup_invalid_manifest_before_pool_creation(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTAGE_ACCESS_DATABASE_DSN", "host=127.0.0.1")
    monkeypatch.setattr(
        "outage_explorer.bootstrap.BoundedPostgresqlPool",
        lambda *args: pytest.fail("Invalid manifest must fail before pool creation"),
    )
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps([{**asdict(PERSONAS[0]), "identity_subject": ""}]))
    assert run(execute_access_setup, ["seed", "--manifest", str(path)]) == 1


def test_missing_configuration_and_failures_sanitized(monkeypatch, capsys):
    monkeypatch.delenv("OUTAGE_ACCESS_DATABASE_DSN", raising=False)
    with pytest.raises(AccessConfigurationError):
        execute_access_setup(AccessSetupInput("migrate"))

    def failure(inputs):
        raise AccessStoreError("password=secret private provider details")

    assert run(failure, ["cleanup"]) == 1
    text = capsys.readouterr().err
    assert "secret" not in text and "failed" in text


def test_shared_iam_setup_signs_explicit_connections_without_cognito(
    database, tmp_path, monkeypatch
):  # noqa: F811
    from outage_explorer.settings import DatabaseSettings

    connection_values = conninfo_to_dict(database)
    # The controlled signer supplies the disposable database's real password;
    # production IAM configuration must never contain a static DSN password.
    password = connection_values.pop("password", "CONTROLLED-TOKEN")
    database_config = DatabaseSettings(
        "iam",
        make_conninfo(**connection_values),
        "controlled.test",
        5432,
        "controlled",
        "us-east-1",
    )
    monkeypatch.setattr(
        "outage_explorer.bootstrap.database_settings", lambda env: database_config
    )
    signed = []

    def sign(self):
        signed.append(len(signed))
        return password

    monkeypatch.setattr("outage_explorer.bootstrap.IAMCredentials.token", sign)
    for name in (
        "COGNITO_ISSUER",
        "COGNITO_DOMAIN",
        "COGNITO_APP_CLIENT_ID",
        "COGNITO_APP_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "seed.json"
    path.write_text(json.dumps([asdict(item) for item in PERSONAS]))
    assert execute_access_setup(AccessSetupInput("migrate")) is None
    assert execute_access_setup(AccessSetupInput("seed", str(path))) == 3
    assert execute_access_setup(AccessSetupInput("cleanup")) == (0, 0)
    assert len(signed) == 3


def test_setup_iam_signer_failure_is_sanitized_before_connection(monkeypatch):
    from unittest.mock import patch

    from outage_explorer.infrastructure.postgresql.migrations import run_migrations

    def signer():
        raise RuntimeError("PRIVATE-CREDENTIAL")

    with patch("psycopg.connect", side_effect=AssertionError("Connected")):
        with pytest.raises(AccessStoreError, match="^Schema migration failed$"):
            run_migrations("host=127.0.0.1 dbname=unused", password_provider=signer)
