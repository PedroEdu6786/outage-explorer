"""Three-resource CLI persistence/recovery with real Parquet and controlled SDK."""

import json
from pathlib import Path
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import MissingDependencyException

from outage_explorer.application.dto import ConnectorArtifactInput
from outage_explorer.application.errors import ConnectorConfigurationError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.bootstrap import (
    execute_connector_artifacts,
    execute_connector_to_s3,
)
from outage_explorer.entrypoints.cli.connector import run
from outage_explorer.infrastructure.resource_metadata import (
    read_candidate,
    read_receipt,
)
from tests.integration.test_connector_cli import (
    SECRET,
    Wire,
    config_file,
    execute,
    models,
    reopen,
    report_path,
    row,
)
from tests.integration.test_s3_artifacts import ControlledS3, failure

ENV = {
    "OUTAGE_S3_BUCKET": "test-bucket",
    "OUTAGE_S3_PREFIX": "connector/",
    "AWS_REGION": "us-east-1",
}


def receipt_path(root, receipt):
    return str(root / "receipts" / (receipt.generation_id + ".json"))


def transfer(client, root, ref, operation="persist", **kwargs):
    return execute_connector_artifacts(
        ConnectorArtifactInput(
            operation,
            str(root),
            str(ref),
            kwargs.pop("config_path", None),
        ),
        environment=ENV,
        client=client,
        **kwargs,
    )


def candidate(root, prior=None, **changes):
    rows = {
        grain: [row(grain, **changes)]
        for grain in ("national", "facility", "generator")
    }
    result, _ = execute(root, rows, prior=prior)
    assert result.report.outcome in ("candidate_verified", "retained_all_excluded")
    return report_path(root, result.report.candidate)


def test_cli_recovers_exact_three_resources_with_eia_disabled(tmp_path, capsys):
    local, restored = tmp_path / "local", tmp_path / "restored"
    first = candidate(local)
    second = candidate(local, first, outage="2")
    original_store, original = reopen(local, second)
    client, receipts = ControlledS3(), []

    def invoke(inputs):
        result = execute_connector_artifacts(inputs, environment=ENV, client=client)
        receipts.append(result)
        return result

    with (
        patch(
            "outage_explorer.infrastructure.eia.source.EiaSource.__init__",
            side_effect=AssertionError("EIA during transfer"),
        ),
        patch("boto3.Session", side_effect=AssertionError("AWS credentials used")),
    ):
        for operation, root in (("persist", local), ("recover", restored)):
            identity = (
                second if operation == "persist" else receipt_path(local, receipts[0])
            )
            assert (
                run(
                    lambda _: pytest.fail("candidate invoked"),
                    [
                        "--operation",
                        operation,
                        "--staging",
                        str(root),
                        "--resources",
                        identity,
                    ],
                    execute_artifacts=invoke,
                )
                == 0
            )
    assert receipts[0] == receipts[1]
    assert read_receipt(receipt_path(local, receipts[0])) == receipts[0]
    recovered_store, _ = reopen(restored, second)
    for grain in ("national", "facility", "generator"):
        assert models(original_store, original, grain) == models(
            recovered_store, original, grain
        )
    assert set(client.objects) == {
        f"connector/generations/{original.generation_id}/{name}.parquet"
        for name in ("national", "facilities", "generators")
    }
    assert len(list(recovered_store.root.iterdir())) == 3
    assert all(SECRET.encode() not in data for data in client.objects.values())
    assert all(body.closed for body in client.closed_bodies)
    output = capsys.readouterr()
    assert "persist_verified" in output.out and "recover_verified" in output.out
    assert SECRET not in output.out + output.err


def test_repeat_persist_verifies_existing_resources_without_overwriting(tmp_path):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    first = transfer(client, root, ref)
    before = dict(client.objects)
    assert transfer(client, root, ref) == first and client.objects == before
    assert len(client.calls) == 12


@pytest.mark.parametrize("target", ["national", "facilities", "generators"])
def test_failed_upload_preserves_prior_and_retry_verifies_three_files(tmp_path, target):
    root = tmp_path / "local"
    first, client = candidate(root), ControlledS3()
    transfer(client, root, first)
    previous = dict(client.objects)
    second = candidate(root, first, outage="2")
    original_put = client.put_object

    def failing(**kwargs):
        if kwargs["Key"].endswith("/" + target + ".parquet"):
            raise failure("AccessDenied")
        return original_put(**kwargs)

    with (
        patch.object(client, "put_object", side_effect=failing),
        pytest.raises(ArtifactError),
    ):
        transfer(client, root, second)
    assert all(client.objects[key] == data for key, data in previous.items())
    receipt = transfer(client, root, second)
    restored = tmp_path / "restored"
    assert transfer(client, restored, receipt_path(root, receipt), "recover") == receipt
    reopen(restored, second)


@pytest.mark.parametrize("target", ["national", "facilities", "generators"])
def test_readback_failure_never_returns_verified_receipt(tmp_path, target):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    client.read_transform = lambda key, data: (
        b"X" * len(data) if key.endswith("/" + target + ".parquet") else data
    )
    with pytest.raises(ArtifactError):
        transfer(client, root, ref)
    assert not (root / "receipts").exists()
    client.read_transform = None
    assert (
        transfer(client, root, ref).generation_id == read_candidate(ref).generation_id
    )


@pytest.mark.parametrize("fault", ["missing", "corrupt", "truncated"])
def test_recovery_failure_preserves_remote_and_prior_local(tmp_path, fault):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    receipt = transfer(client, root, ref)
    key = receipt.resources[0].object.key
    if fault == "missing":
        del client.objects[key]
    elif fault == "corrupt":
        client.objects[key] = b"X" * len(client.objects[key])
    else:
        client.objects[key] = client.objects[key][:-1]
    before = dict(client.objects)
    with pytest.raises(ArtifactError):
        transfer(client, tmp_path / "recovery", receipt_path(root, receipt), "recover")
    assert before == client.objects
    assert not list((tmp_path / "recovery" / "objects").iterdir())
    reopen(root, ref)


def test_resource_limits_and_corrupt_candidate_precede_sdk_construction(tmp_path):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    config = config_file(root, {"artifact": {"objects": 1}})
    with pytest.raises(ArtifactLimitError):
        transfer(client, root, ref, config_path=config)
    assert not client.calls
    metadata = read_candidate(ref)
    (root / "objects" / metadata.resources[0].object.key).write_bytes(b"corrupt")
    with (
        patch("boto3.Session", side_effect=AssertionError("AWS before validation")),
        pytest.raises(ArtifactError),
    ):
        execute_connector_artifacts(
            ConnectorArtifactInput("persist", str(root), ref), environment=ENV
        )


def test_recovery_requires_fresh_staging_before_external_work(tmp_path):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    receipt = transfer(client, root, ref)
    before = list(client.calls)
    with pytest.raises(ConnectorConfigurationError):
        transfer(client, root, receipt_path(root, receipt), "recover")
    assert client.calls == before
    reopen(root, ref)


@pytest.mark.parametrize(
    "change",
    [
        {"OUTAGE_S3_BUCKET": "https://untrusted"},
        {"OUTAGE_S3_PREFIX": "../"},
        {"AWS_REGION": "invalid"},
        {"OUTAGE_S3_BUCKET": ""},
    ],
)
def test_invalid_target_configuration_does_no_work(tmp_path, change):
    root = tmp_path / "never-created"
    with (
        patch("boto3.Session", side_effect=AssertionError("AWS constructed")),
        pytest.raises(ConnectorConfigurationError),
    ):
        execute_connector_artifacts(
            ConnectorArtifactInput("recover", str(root), "absent.json"),
            environment=ENV | change,
        )
    assert not root.exists()


def test_cli_failure_output_omits_sdk_secret_and_verified_reference(tmp_path, capsys):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    client.put_faults = [failure("AccessDenied")]
    assert (
        run(
            lambda _: pytest.fail("candidate"),
            ["--operation", "persist", "--staging", str(root), "--resources", ref],
            execute_artifacts=lambda inputs: execute_connector_artifacts(
                inputs, environment=ENV, client=client
            ),
        )
        == 1
    )
    output = capsys.readouterr()
    assert (
        "verified" not in output.out
        and "synthetic-sdk-secret" not in output.out + output.err
    )


def test_injected_credential_session_uses_bounded_sdk_configuration(tmp_path):
    root = tmp_path / "local"
    ref, client, calls = candidate(root), ControlledS3(), []

    class Session:
        def client(self, service, *, config):
            assert service == "s3" and config.retries["total_max_attempts"] == 1
            assert config.connect_timeout == 10 and config.read_timeout == 10
            assert config.max_pool_connections >= 3
            return client

    def provider(**kwargs):
        calls.append(kwargs)
        return Session()

    client.close = lambda: calls.append("closed")
    result = execute_connector_artifacts(
        ConnectorArtifactInput("persist", str(root), ref),
        environment=ENV | {"AWS_PROFILE": "synthetic-profile"},
        session_factory=provider,
    )
    assert result.generation_id == read_candidate(ref).generation_id
    assert calls == [
        {"profile_name": "synthetic-profile", "region_name": "us-east-1"},
        "closed",
    ]


@pytest.mark.parametrize("tamper", ["rows", "key", "duplicate", "size"])
def test_recovery_rejects_descriptor_tampering_and_byte_caps(tmp_path, tamper):
    root = tmp_path / "local"
    ref, client = candidate(root), ControlledS3()
    receipt = transfer(client, root, ref)
    path = tmp_path / "tampered.json"
    value = json.loads(Path(receipt_path(root, receipt)).read_text())
    config = None
    if tamper == "rows":
        value["resources"][0]["row_count"] += 1
    elif tamper == "key":
        value["resources"][0]["object"]["key"] = "wrong/national.parquet"
    elif tamper == "duplicate":
        value["resources"].append(value["resources"][0])
    else:
        config = config_file(tmp_path / "limited", {"artifact": {"total_bytes": 1}})
    path.write_text(json.dumps(value))
    with pytest.raises((ArtifactError, ConnectorConfigurationError)):
        transfer(
            client, tmp_path / "restored", str(path), "recover", config_path=config
        )
    assert all(body.closed for body in client.closed_bodies)


def test_cli_help_and_arguments_never_construct_durable_client(capsys):
    def forbidden(_):
        pytest.fail("operation executed")

    with pytest.raises(SystemExit) as error:
        run(
            forbidden, ["--operation", "recover", "--help"], execute_artifacts=forbidden
        )
    assert error.value.code == 0
    assert (
        run(
            forbidden,
            ["--operation", "persist", "--start", "2026-09-01"],
            execute_artifacts=forbidden,
        )
        == 2
    )
    assert "recover" in capsys.readouterr().out


@pytest.mark.parametrize("file_staging", [False, True])
@pytest.mark.parametrize(
    "start,end", [("2026-09-01", "2026-09-01"), ("2026-04-02", "2026-10-01")]
)
def test_default_candidate_cli_persists_three_resources_to_s3(
    tmp_path, capsys, file_staging, start, end
):
    root = tmp_path / "candidate"
    client, wire, results = (
        ControlledS3(),
        Wire(
            {
                grain: [row(grain, period=start)]
                for grain in ("national", "facility", "generator")
            }
        ),
        [],
    )

    def durable(inputs):
        result = execute_connector_to_s3(
            inputs,
            environment=ENV | {"EIA_API_KEY": SECRET},
            transport=wire,
            client=client,
        )
        results.append(result)
        return result

    if file_staging:
        path = config_file(root, {"start": start, "end": end, "staging": str(root)})
        args = ["--config", path]
    else:
        args = ["--start", start, "--end", end, "--staging", str(root)]
    assert (
        run(lambda _: pytest.fail("local-only executed"), args, execute_durable=durable)
        == 0
    )
    result = results[0]
    assert wire.closed and result.receipt is not None and result.error is None
    assert result.candidate.report.interval.start.isoformat() == start
    assert result.candidate.report.interval.end.isoformat() == end
    assert all(
        request.url.params["length"] == "500"
        for request in wire.calls
        if request.url.path.endswith("/data/")
    )
    assert (
        result.receipt.generation_id == result.candidate.report.candidate.generation_id
    )
    assert len(client.objects) == 3
    receipt = transfer(
        client, tmp_path / "restored", receipt_path(root, result.receipt), "recover"
    )
    assert receipt == result.receipt
    output = capsys.readouterr()
    assert "candidate_s3_verified" in output.out
    assert (
        "candidate_s3_complete" in output.err and "s3_readback_verified" in output.err
    )
    assert SECRET not in output.out + output.err


def test_default_candidate_missing_s3_config_fails_before_eia_or_staging(
    tmp_path, capsys
):
    root, wire = tmp_path / "candidate", Wire()
    with patch("boto3.Session", side_effect=AssertionError("AWS accessed")):
        code = run(
            lambda _: pytest.fail("local-only executed"),
            ["--start", "2026-09-01", "--end", "2026-09-01", "--staging", str(root)],
            execute_durable=lambda inputs: execute_connector_to_s3(
                inputs, environment={"EIA_API_KEY": SECRET}, transport=wire
            ),
        )
    assert code == 2 and wire.closed and not wire.calls and not root.exists()
    assert "failed configuration" in capsys.readouterr().out


def test_s3_failure_preserves_local_candidate_for_source_disabled_retry(
    tmp_path, capsys
):
    root, client, wire = tmp_path / "candidate", ControlledS3(), Wire()
    client.put_faults = [failure("AccessDenied")]
    assert (
        run(
            lambda _: pytest.fail("local-only executed"),
            ["--start", "2026-09-01", "--end", "2026-09-01", "--staging", str(root)],
            execute_durable=lambda inputs: execute_connector_to_s3(
                inputs,
                environment=ENV | {"EIA_API_KEY": SECRET},
                transport=wire,
                client=client,
            ),
        )
        == 1
    )
    output = capsys.readouterr()
    assert (
        "failed persistence" in output.out and "candidate_s3_verified" not in output.out
    )
    assert "error=artifact_integrity" in output.out
    assert SECRET not in output.out + output.err
    text = next(
        line.removeprefix("local_resources=")
        for line in output.out.splitlines()
        if line.startswith("local_resources=")
    )
    _, local_candidate = reopen(root, text)
    report = json.loads(next((root / "runs").glob("*/report.json")).read_text())
    assert report["outcome"] == "candidate_verified" and not report["published"]
    with patch(
        "outage_explorer.infrastructure.eia.source.EiaSource.__init__",
        side_effect=AssertionError("EIA used during retry"),
    ):
        receipt = transfer(client, root, text)
    assert receipt.generation_id == local_candidate.generation_id


def test_local_only_rejects_explicit_artifact_operation_before_io(capsys):
    assert (
        run(
            lambda _: pytest.fail("candidate executed"),
            ["--operation", "persist", "--local-only"],
            execute_artifacts=lambda _: pytest.fail("S3 executed"),
        )
        == 2
    )
    assert "failed configuration" in capsys.readouterr().out


def test_missing_sdk_login_dependency_has_safe_actionable_error(tmp_path, capsys):
    root = tmp_path / "candidate"
    ref = candidate(root)

    def provider(**kwargs):
        raise MissingDependencyException(msg=SECRET)

    assert (
        run(
            lambda _: pytest.fail("candidate invoked"),
            [
                "--operation",
                "persist",
                "--staging",
                str(root),
                "--resources",
                ref,
            ],
            execute_artifacts=lambda inputs: execute_connector_artifacts(
                inputs, environment=ENV, session_factory=provider
            ),
        )
        == 1
    )
    output = capsys.readouterr()
    assert "failed aws_dependency" in output.out and "make setup" in output.out
    assert SECRET not in output.out + output.err


def test_installed_sdk_constructs_login_profile_offline(tmp_path, monkeypatch):
    config = tmp_path / "aws-config"
    config.write_text(
        "[profile controlled-login]\nlogin_session = arn:aws:iam::123456789012:user/synthetic\nregion = us-east-1\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv(
        "AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "absent-credentials")
    )
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    cached = {
        "access_key": "synthetic-key",
        "secret_key": "synthetic-secret",
        "token": "synthetic-token",
        "expiry_time": "2030-01-01T00:00:00Z",
        "account_id": "123456789012",
    }
    with (
        patch(
            "botocore.credentials.LoginCredentialFetcher.load_cached_credentials",
            return_value=cached,
        ),
        patch("socket.socket.connect", side_effect=AssertionError("network access")),
        patch("socket.getaddrinfo", side_effect=AssertionError("network access")),
    ):
        session = boto3.Session(profile_name="controlled-login")
        client = session.client("s3")
        assert session.get_credentials().method == "login"
        client.close()


def test_default_candidate_cli_uses_independent_parallel_transfer_setting(tmp_path):
    root = tmp_path / "parallel-default"
    client = ControlledS3()
    path = config_file(root, {"workers": {"endpoint_workers": 3, "s3_workers": 3}})
    from tests.integration.test_connector_cli import inputs

    result = execute_connector_to_s3(
        inputs(root, config_path=path),
        environment=ENV | {"EIA_API_KEY": SECRET},
        transport=Wire(),
        client=client,
    )
    assert result.error is None
    assert (
        result.receipt.generation_id == result.candidate.report.candidate.generation_id
    )
    assert all(body.closed for body in client.closed_bodies)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"candidate":{},"candidate":{}}',
        b"[]",
        b"not json",
        b" " * 65537,
    ],
)
def test_bounded_local_metadata_rejects_bad_documents_before_sdk(tmp_path, payload):
    root = tmp_path / "local"
    metadata = tmp_path / "invalid.json"
    metadata.write_bytes(payload)
    client = ControlledS3()
    with (
        patch(
            "boto3.Session",
            side_effect=AssertionError("AWS before metadata validation"),
        ),
        pytest.raises((ArtifactError, ConnectorConfigurationError)),
    ):
        execute_connector_artifacts(
            ConnectorArtifactInput("persist", str(root), str(metadata)),
            environment=ENV,
            client=client,
        )
    assert not client.calls and not root.exists()
