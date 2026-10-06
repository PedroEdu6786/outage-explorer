"""CLI graph recovery with real Parquet and controlled SDK, EIA disabled."""

import hashlib
import json
from dataclasses import replace
from unittest.mock import patch

import boto3
import pytest
from botocore.exceptions import MissingDependencyException

from outage_explorer.application.dto import ConnectorArtifactInput
from outage_explorer.application.errors import ConnectorConfigurationError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
)
from outage_explorer.application.services.connector_artifacts import (
    PersistConnectorArtifacts,
)
from outage_explorer.bootstrap import (
    execute_connector_artifacts,
    execute_connector_to_s3,
)
from outage_explorer.entrypoints.cli.connector import run
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.evidence import replay_evidence
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_cli import (
    ARTIFACT,
    MODEL,
    SECRET,
    Wire,
    config_file,
    execute,
    models,
    reopen,
    row,
)
from tests.integration.test_s3_artifacts import ControlledS3, adapter, failure

ENV = {
    "OUTAGE_S3_BUCKET": "test-bucket",
    "OUTAGE_S3_PREFIX": "connector/",
    "AWS_REGION": "us-east-1",
}


def transfer(client, root, ref, operation="persist", **kwargs):
    return execute_connector_artifacts(
        ConnectorArtifactInput(
            operation,
            str(root),
            f"{ref.key}:{ref.byte_count}",
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
    return result.report.manifest


def test_cli_recovers_complete_retained_graph_exactly_with_eia_disabled(
    tmp_path, capsys
):
    local, restored = tmp_path / "local", tmp_path / "restored"
    rows = {
        grain: [
            row(grain, outage="1"),
            row(grain, outage="2"),
            row(grain, outage="1"),
            row(grain, period="2026-09-02"),
        ]
        for grain in ("national", "facility", "generator")
    }
    initial, _ = execute(local, rows)
    first = initial.report.manifest
    # Incoming invalid values retain earlier modeled rows and evidence origins.
    second = candidate(local, first, outage="invalid")
    original_store, original = reopen(local, second)
    assert original.base_manifest_object == first
    assert original.inherited_evidence
    graph = LocalConnectorEvidence(original_store).graph(second, MODEL)
    client, receipts = ControlledS3(), []

    def invoke(inputs):
        result = execute_connector_artifacts(inputs, environment=ENV, client=client)
        receipts.append(result)
        return result

    with (
        patch(
            "outage_explorer.infrastructure.eia.source.EiaSource.__init__",
            side_effect=AssertionError("EIA used during transfer"),
        ),
        patch(
            "boto3.Session",
            side_effect=AssertionError("AWS credentials used in controlled test"),
        ),
    ):
        for operation, root in (("persist", local), ("recover", restored)):
            assert (
                run(
                    lambda _: pytest.fail("candidate invoked"),
                    [
                        "--operation",
                        operation,
                        "--staging",
                        str(root),
                        "--manifest",
                        f"{second.key}:{second.byte_count}",
                    ],
                    execute_artifacts=invoke,
                )
                == 0
            )
    recovered_store, recovered = reopen(restored, second)
    assert recovered == original
    for expected, actual in zip(
        original.inherited_evidence, recovered.inherited_evidence, strict=True
    ):
        assert list(replay_evidence(original_store, expected)) == list(
            replay_evidence(recovered_store, actual)
        )
    assert receipts[0] == receipts[1]
    assert receipts[0].objects == len(graph)
    for grain in ("national", "facility", "generator"):
        assert models(original_store, original, grain) == models(
            recovered_store, recovered, grain
        )
    assert all(
        b"synthetic-only-connector-secret" not in data
        for data in client.objects.values()
    )
    puts = [key for kind, key in client.calls if kind == "put"]
    assert puts[-1].endswith(second.key)
    # Verification derives bounded local day partitions, outside the durable graph.
    from outage_explorer.infrastructure.parquet.partitions import stage_dates

    derived = {
        ref.object.key
        for bundle in (*recovered.evidence, *recovered.inherited_evidence)
        for refs in stage_dates(recovered_store, bundle).values()
        for ref in refs
    }
    assert set(ref.key for ref in graph) | derived == {
        path.name for path in recovered_store.root.iterdir()
    }
    output = capsys.readouterr()
    assert "persist_verified" in output.out
    assert (
        "s3_persistence_started" in output.err and "role=final_manifest" in output.err
    )
    assert output.err.index("durable_graph_readback_started") < output.err.index(
        "s3_persistence_verified"
    )
    assert "recovery_started" in output.err and "eia=disabled" in output.err
    assert "graph_restore_verified" in output.err and "recovery_verified" in output.err
    assert "synthetic-only-connector-secret" not in output.err


def test_repeat_persist_verifies_existing_graph_without_overwriting(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    first = transfer(client, root, ref)
    before = dict(client.objects)
    second = transfer(client, root, ref)
    assert first == second and client.objects == before


@pytest.mark.parametrize("target", ["dependency", "final"])
def test_failed_upload_preserves_prior_objects_and_retry_verifies_complete_graph(
    tmp_path, target
):
    root = tmp_path / "local"
    first = candidate(root)
    client = ControlledS3()
    transfer(client, root, first)
    previous = dict(client.objects)
    second = candidate(root, first, outage="2")
    store, _ = reopen(root, second)
    graph = LocalConnectorEvidence(store).graph(second, MODEL)
    fail_key = graph[0].key if target == "dependency" else second.key
    original_put = client.put_object

    def failing(**kwargs):
        if kwargs["Key"].endswith(fail_key):
            raise failure("AccessDenied")
        return original_put(**kwargs)

    with patch.object(client, "put_object", side_effect=failing):
        with pytest.raises(ArtifactError):
            transfer(client, root, second)
    assert all(client.objects[key] == value for key, value in previous.items())
    assert "connector/objects/" + second.key not in client.objects
    transfer(client, root, second)
    recovered = tmp_path / "recovered"
    transfer(client, recovered, second, "recover")
    assert reopen(recovered, second)[1] == reopen(root, second)[1]


@pytest.mark.parametrize("target", ["dependency", "final", "full_replay"])
def test_readback_failure_never_returns_verified_receipt(tmp_path, target):
    root = tmp_path / "local"
    ref = candidate(root)
    store, _ = reopen(root, ref)
    graph = LocalConnectorEvidence(store).graph(ref, MODEL)
    client = ControlledS3()
    final_gets = 0

    def corrupt(key, data):
        nonlocal final_gets
        if key.endswith(ref.key):
            final_gets += 1
        if (
            (target == "dependency" and key.endswith(graph[0].key))
            or (target == "final" and key.endswith(ref.key))
            or (target == "full_replay" and key.endswith(ref.key) and final_gets > 1)
        ):
            return b"X" * len(data)
        return data

    client.read_transform = corrupt
    with pytest.raises(ArtifactError):
        transfer(client, root, ref)
    if target == "dependency":
        assert "connector/objects/" + ref.key not in client.objects
    client.read_transform = None
    assert transfer(client, root, ref).manifest == ref


@pytest.mark.parametrize("fault", ["missing", "corrupt", "truncated"])
def test_recovery_incomplete_graph_fails_preserving_remote_and_prior_local(
    tmp_path, fault
):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    transfer(client, root, ref)
    store, _ = reopen(root, ref)
    dependency = LocalConnectorEvidence(store).graph(ref, MODEL)[0]
    key = "connector/objects/" + dependency.key
    if fault == "missing":
        del client.objects[key]  # Test fixture fault only; adapter exposes no delete.
    elif fault == "corrupt":
        client.objects[key] = b"X" * len(client.objects[key])
    else:
        client.objects[key] = client.objects[key][:-1]
    before = dict(client.objects)
    with pytest.raises(ArtifactError):
        transfer(client, tmp_path / "recovery", ref, "recover")
    assert before == client.objects
    reopen(root, ref)


def test_recovery_rejects_conflicting_dependency_identity(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    transfer(client, root, ref)
    value = json.loads(client.objects["connector/objects/" + ref.key])
    repeated = json.loads(json.dumps(value["dispositions"][0]))
    repeated["object"]["byte_count"] += 1
    value["dispositions"].append(repeated)
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(data).hexdigest()
    bad = StoredObject(digest, digest, len(data))
    client.objects["connector/objects/" + digest] = data
    with pytest.raises(ArtifactError, match="Conflicting"):
        transfer(client, tmp_path / "recovery", bad, "recover")


def test_graph_limits_and_invalid_prior_precede_sdk_construction(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    limited = LocalConnectorEvidence(
        LocalParquetStore(root / "objects", replace(ARTIFACT, objects=1))
    )
    with pytest.raises(ArtifactLimitError):
        PersistConnectorArtifacts(limited, adapter(client)).execute(ref, MODEL)
    assert not client.calls
    (root / "objects" / ref.key).write_bytes(b"corrupt")
    with patch(
        "boto3.Session", side_effect=AssertionError("AWS constructed before validation")
    ):
        with pytest.raises(ArtifactError):
            execute_connector_artifacts(
                ConnectorArtifactInput(
                    "persist", str(root), f"{ref.key}:{ref.byte_count}"
                ),
                environment=ENV,
            )


def test_recovery_requires_fresh_staging_before_external_work(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    with pytest.raises(ConnectorConfigurationError):
        transfer(client, root, ref, "recover")
    assert not client.calls
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
    with patch("boto3.Session", side_effect=AssertionError("AWS constructed")):
        with pytest.raises(ConnectorConfigurationError):
            execute_connector_artifacts(
                ConnectorArtifactInput("recover", str(root), "a" * 64 + ":10"),
                environment=ENV | change,
            )
    assert not root.exists()


def test_cli_failure_output_omits_sdk_secret_and_verified_reference(tmp_path, capsys):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    client.put_faults = [failure("AccessDenied")]
    assert (
        run(
            lambda _: pytest.fail("candidate called"),
            [
                "--operation",
                "persist",
                "--staging",
                str(root),
                "--manifest",
                f"{ref.key}:{ref.byte_count}",
            ],
            execute_artifacts=lambda inputs: execute_connector_artifacts(
                inputs, environment=ENV, client=client
            ),
        )
        == 1
    )
    output = capsys.readouterr().out
    assert (
        "verified" not in output
        and "manifest=" not in output
        and "synthetic-sdk-secret" not in output
    )


def test_injected_credential_session_uses_bounded_sdk_configuration(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    calls = []

    class Session:
        def client(self, service, *, config):
            assert service == "s3" and config.retries["total_max_attempts"] == 1
            assert config.connect_timeout == 10 and config.read_timeout == 10
            return client

    def provider(**kwargs):
        calls.append(kwargs)
        return Session()

    client.close = lambda: calls.append("closed")
    result = execute_connector_artifacts(
        ConnectorArtifactInput("persist", str(root), f"{ref.key}:{ref.byte_count}"),
        environment=ENV | {"AWS_PROFILE": "synthetic-profile"},
        session_factory=provider,
    )
    assert result.manifest == ref
    assert calls == [
        {"profile_name": "synthetic-profile", "region_name": "us-east-1"},
        "closed",
    ]


def test_recovery_rejects_graph_byte_caps_and_schema_descriptor_tampering(tmp_path):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    transfer(client, root, ref)
    config = tmp_path / "small.json"
    config.write_text(json.dumps({"artifact": {"total_bytes": ref.byte_count}}))
    with pytest.raises(ArtifactLimitError):
        transfer(client, tmp_path / "limited", ref, "recover", config_path=str(config))
    value = json.loads(client.objects["connector/objects/" + ref.key])
    value["modeled"][0]["row_count"] += 1
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(data).hexdigest()
    bad = StoredObject(digest, digest, len(data))
    client.objects["connector/objects/" + digest] = data
    with pytest.raises(ArtifactError):
        transfer(client, tmp_path / "tampered", bad, "recover")


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
def test_default_candidate_cli_persists_complete_graph_to_s3(
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
    assert result.receipt.manifest == result.candidate.report.manifest
    assert len(client.objects) == result.receipt.objects
    receipt = transfer(
        client, tmp_path / "restored", result.receipt.manifest, "recover"
    )
    assert receipt == result.receipt
    output = capsys.readouterr()
    assert "candidate_s3_verified" in output.out
    assert (
        "candidate_s3_complete" in output.err
        and "s3_persistence_verified" in output.err
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
        line.removeprefix("local_manifest=")
        for line in output.out.splitlines()
        if line.startswith("local_manifest=")
    )
    digest, count = text.split(":")
    ref = StoredObject(digest, digest, int(count))
    _, candidate_manifest = reopen(root, ref)
    assert candidate_manifest.manifest_object == ref
    report = json.loads(next((root / "runs").glob("*/report.json")).read_text())
    assert report["outcome"] == "candidate_verified" and not report["published"]
    with patch(
        "outage_explorer.infrastructure.eia.source.EiaSource.__init__",
        side_effect=AssertionError("EIA used during retry"),
    ):
        receipt = transfer(client, root, ref)
    assert receipt.manifest == ref


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
                "--manifest",
                f"{ref.key}:{ref.byte_count}",
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
    assert result.receipt.manifest == result.candidate.report.manifest
    assert all(body.closed for body in client.closed_bodies)
