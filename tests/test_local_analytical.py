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
        assert "--property=SupplementaryGroups=991" in command


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
