import importlib.util
import io
import json
import shlex
import subprocess
import sys
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import boto3
import pytest

SPEC = importlib.util.spec_from_file_location(
    "local_analytical", Path(__file__).parents[1] / "scripts/local_analytical.py"
)
assert SPEC is not None and SPEC.loader is not None
local = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(local)


def credentials(key="first"):
    return {
        "Version": 1,
        "AccessKeyId": key,
        "SecretAccessKey": "controlled-secret",
        "SessionToken": "controlled-token",
        "Expiration": (datetime.now(UTC) + timedelta(minutes=4)).isoformat(),
    }


def test_existing_sdk_session_reads_rotated_credentials(tmp_path, monkeypatch):
    """Long-lived S3 clients must renew too, not just new IAM signer processes."""
    document = tmp_path / "credentials.json"
    document.write_text(json.dumps({"local": credentials()}))
    reader = tmp_path / "reader.py"
    reader.write_text(
        local.READER.replace("/run/outage-api/credentials.json", str(document))
    )
    config = tmp_path / "config"
    config.write_text(
        "[profile local]\ncredential_process = "
        f"{shlex.quote(sys.executable)} {shlex.quote(str(reader))} local\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "empty"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    session = boto3.Session(profile_name="local")
    provider = session.get_credentials()
    assert provider.get_frozen_credentials().access_key == "first"
    document.write_text(json.dumps({"local": credentials("replacement")}))
    assert provider.get_frozen_credentials().access_key == "replacement"


def test_reject_expired_credentials_before_copy(monkeypatch):
    value = credentials()
    value["Expiration"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(local, "run", lambda *args, **kwargs: json.dumps(value))
    with pytest.raises(ValueError, match="expired"):
        local.export_credentials(["local"])


def test_private_atomic_transfer_never_puts_keys_in_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        local, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    local.install({"local": credentials()}, local.credential_config(["local"]))
    args, kwargs = calls[0]
    assert "controlled-secret" not in str(args)
    assert "credentials.json.new /run/outage-api/credentials.json" in args[-1]
    with tarfile.open(fileobj=io.BytesIO(kwargs["data"])) as archive:
        assert all(
            item.mode == 0o600 and item.uid == item.gid == 65534 for item in archive
        )
        assert archive.extractfile("aws-credentials.new").read() == b""


def test_profile_cannot_inject_credential_command():
    with pytest.raises(ValueError):
        local.credential_config(["local; echo unsafe"])


def test_cli_failures_do_not_expose_credential_diagnostics(monkeypatch):
    monkeypatch.setattr(
        local.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 1, b"secret", b"secret"
        ),
    )
    with pytest.raises(RuntimeError) as error:
        local.run(["aws"])
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "state,expected",
    [
        ("loaded", ["sudo", "systemctl", "restart", "outage-api-local"]),
        ("not-found", None),
    ],
)
def test_service_is_restarted_or_recreated_after_a_stop(monkeypatch, state, expected):
    calls = []

    def fake(arguments, **kwargs):
        calls.append(arguments[len(local.SSH) :])
        if "stat" in arguments:
            return b"997"
        return state.encode() if "show" in arguments else b""

    monkeypatch.setattr(local, "run", fake)
    local.start_service()
    command = calls[-1]
    if expected is not None:
        assert command == expected
    else:
        assert command[:3] == ["sudo", "systemd-run", "--unit=outage-api-local"]
        assert command[-2:] == [local.PYTHON, "/run/outage-api/start.py"]
        assert "--property=User=65534" in command
        assert "--property=SupplementaryGroups=997" in command


@pytest.mark.parametrize("group", [b"0", b"bad", b"997;false", b"-1"])
def test_invalid_socket_group_never_starts_service(monkeypatch, group):
    calls = []

    def fake(arguments, **kwargs):
        calls.append(arguments)
        return group if "stat" in arguments else b"not-found"

    monkeypatch.setattr(local, "run", fake)
    with pytest.raises(ValueError, match="socket group"):
        local.start_service()
    assert not any("systemd-run" in args for args in calls)


def reviewed_configs(tmp_path, *, reviewed=True):
    from dataclasses import asdict
    from datetime import date

    from outage_explorer.infrastructure.sql_validation.configuration import (
        InspectionProfile,
        InspectionReview,
    )
    from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
        InspectionBounds,
    )
    from outage_explorer.infrastructure.worker_runtime.configuration import (
        RuntimeEvidence,
        RuntimeProfile,
    )

    profile = RuntimeProfile(
        "sha256:" + "a" * 64,
        "unix:///run/docker.sock",
        "linux/arm64",
        "controlled",
        "controlled",
        temporary_backend="quota-disk",
    )
    evidence = RuntimeEvidence(
        profile.identity,
        *("b" * 64 for _ in range(5)),
        "Controlled test only",
        date(2026, 10, 7),
        "local-preview-sql",
    )
    parser = InspectionProfile(
        InspectionBounds(4, 1, 268435456, 1, 1024, 65536, 10000, 64),
        local.PYTHON,
        "/usr/bin/prlimit",
        "/usr/bin/setpriv",
        "/var/lib/outage-runtime-validation/parser-ownership",
        *("c" * 64 for _ in range(3)),
    )
    review = InspectionReview(
        parser.identity, "d" * 64, "e" * 64, "Controlled test only", date(2026, 10, 7)
    )
    paths = (tmp_path / "runtime.json", tmp_path / "parser.json")
    for path, model, record in zip(
        paths, (profile, parser), (evidence, review), strict=True
    ):
        path.write_text(
            json.dumps(
                {
                    "profile": asdict(model),
                    "evidence": asdict(record) if reviewed else None,
                },
                default=str,
            )
        )
    return paths


@pytest.mark.parametrize("mode", ["iam", "password"])
def test_configure_installs_complete_private_api_without_starting(
    tmp_path, monkeypatch, mode
):
    from psycopg.conninfo import conninfo_to_dict

    ca = tmp_path / "CA with spaces.pem"
    ca.write_text("controlled public CA")
    env = {
        "COGNITO_APP_CLIENT_SECRET": "controlled-config-secret",
        "AWS_PROFILE": "local",
        "OUTAGE_ACCESS_DATABASE_MODE": mode,
        "EIA_API_KEY": "not-for-api",
        "UNRELATED_SECRET": "never-transfer",
        "PYTHONPATH": "/untrusted",
        "AWS_SECRET_ACCESS_KEY": "not-for-configuration",
    }
    if mode == "iam":
        env["OUTAGE_ACCESS_DATABASE_SSLROOTCERT"] = str(ca)
    else:
        from psycopg.conninfo import make_conninfo

        env["OUTAGE_ACCESS_DATABASE_DSN"] = make_conninfo(
            host="db.test", password="controlled-db-secret", sslrootcert=str(ca)
        )
    calls = []
    monkeypatch.setattr(
        local, "run", lambda args, **kwargs: calls.append((args, kwargs))
    )
    local.configure(env, *reviewed_configs(tmp_path))
    args, kwargs = calls[0]
    assert "controlled-config-secret" not in str(args)
    assert "systemd-run" not in str(args) and "is-active" in args[-1]
    with tarfile.open(fileobj=io.BytesIO(kwargs["data"])) as archive:
        assert all(
            item.uid == item.gid == 65534 and item.mode == 0o600 for item in archive
        )
        assert set(archive.getnames()) == {
            "start.py",
            "runtime.json",
            "parser.json",
            "environment.json",
            "rds-ca.pem",
        }
        values = json.load(archive.extractfile("environment.json"))
        assert values["COGNITO_APP_CLIENT_SECRET"] == "controlled-config-secret"
        assert (
            not {
                "EIA_API_KEY",
                "UNRELATED_SECRET",
                "PYTHONPATH",
                "AWS_SECRET_ACCESS_KEY",
            }
            & values.keys()
        )
        if mode == "iam":
            assert (
                values["OUTAGE_ACCESS_DATABASE_SSLROOTCERT"]
                == "/run/outage-api/rds-ca.pem"
            )
        else:
            assert "OUTAGE_ACCESS_DATABASE_SSLROOTCERT" not in values
        if mode == "password":
            dsn = conninfo_to_dict(values["OUTAGE_ACCESS_DATABASE_DSN"])
            assert dsn["sslrootcert"] == "/run/outage-api/rds-ca.pem"
            assert dsn["password"] == "controlled-db-secret"


def test_configure_rejects_unreviewed_candidate_before_transfer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        local, "run", lambda *a, **kw: pytest.fail("unexpected host operation")
    )
    with pytest.raises(ValueError, match="reviewed"):
        local.configure({}, *reviewed_configs(tmp_path, reviewed=False))


def test_native_configuration_does_not_start_or_export_credentials(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(local.sys, "platform", "linux")
    monkeypatch.setattr(local, "ROOT", tmp_path)
    monkeypatch.setattr(local, "SSH", ["unused"])
    calls = []
    monkeypatch.setattr(local, "configure", lambda *args: calls.append(args))
    monkeypatch.setattr(
        local,
        "export_credentials",
        lambda *a: pytest.fail("unexpected credential export"),
    )
    assert (
        local.main(
            [
                "--native",
                "--configure",
                "--config",
                "runtime.json",
                "--inspection-config",
                "parser.json",
            ]
        )
        == 0
    )
    assert local.SSH == [] and len(calls) == 1


def test_checked_in_entrypoint_executes_only_configured_environment(
    tmp_path, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "local_api_entrypoint",
        Path(__file__).parents[1] / "scripts/local_api_entrypoint.py",
    )
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    (tmp_path / "environment.json").write_text(
        json.dumps({"PATH": "/usr/bin:/bin", "COGNITO_APP_CLIENT_SECRET": "controlled"})
    )
    monkeypatch.setattr(entry, "RUNTIME", tmp_path)
    monkeypatch.setenv("UNRELATED_SECRET", "never-inherit")
    calls = []
    monkeypatch.setattr(entry.os, "execve", lambda *args: calls.append(args))
    entry.main()
    executable, args, environment = calls[0]
    assert executable == local.PYTHON
    assert "outage_explorer.entrypoints.http.analytical_startup" in args
    assert "--inspection-config" in args and args[-1] == "8000"
    assert "UNRELATED_SECRET" not in environment


def test_worker_launcher_loads_env_and_defaults_private_staging(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "run_worker", Path(__file__).parents[1] / "scripts/run_worker.py"
    )
    assert spec is not None and spec.loader is not None
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    (tmp_path / ".env").write_text(
        "EIA_API_KEY=from-file\nCOGNITO_OAUTH_SCOPES=a b c\n"
    )
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    monkeypatch.delenv("OUTAGE_REFRESH_STAGING", raising=False)
    monkeypatch.setenv("EIA_API_KEY", "from-process")
    env = worker.environment()
    assert env["EIA_API_KEY"] == "from-process"  # Explicit environment wins.
    assert env["COGNITO_OAUTH_SCOPES"] == "a b c"
    assert env["OUTAGE_REFRESH_STAGING"].endswith("data/refresh-local")
    monkeypatch.setenv("OUTAGE_REFRESH_STAGING", "/custom")
    assert worker.environment()["OUTAGE_REFRESH_STAGING"] == "/custom"


def test_password_mode_only_exports_storage_profile():
    assert local.credential_profiles(
        {"AWS_PROFILE": "storage", "OUTAGE_ACCESS_DATABASE_MODE": "password"}
    ) == ["storage"]


def test_iam_mode_exports_both_required_profiles():
    assert local.credential_profiles(
        {
            "AWS_PROFILE": "storage",
            "OUTAGE_ACCESS_DATABASE_MODE": "iam",
            "OUTAGE_ACCESS_DATABASE_PROFILE": "database",
        }
    ) == ["database", "storage"]
