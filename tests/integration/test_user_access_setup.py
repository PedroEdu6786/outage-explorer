"""Explicit CLI setup remains independent of AWS and connector execution."""

import json
import subprocess
import sys
from dataclasses import asdict

import pytest

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
