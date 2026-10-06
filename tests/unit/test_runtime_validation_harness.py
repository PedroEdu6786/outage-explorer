"""Controlled validation-harness checks; never invoke Docker or source services."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import retain_result
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.docker import ControlResult
from tests.runtime_validation import (
    EvidenceReport,
    RepresentativeInputs,
    RuntimeHarness,
    measured_workload,
    opted_in,
    private_directory,
    read_representative_inputs,
    record_gate,
)


@pytest.fixture
def profile(tmp_path):
    return RuntimeProfile(
        "sha256:" + "a" * 64,
        "unix:///tmp/validation.sock",
        "linux/amd64",
        "controlled",
        "controlled",
        staging_root=str(tmp_path / "staging"),
        cache_root=str(tmp_path / "cache"),
        result_root=str(tmp_path / "results"),
    )


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "not runtime_docker",
        "runtime_docker or runtime_measurements",
        "acceptance",
        "runtime_docker and not live_provider",
    ],
)
def test_no_marker_optin_even_with_profile(expression):
    assert not opted_in(expression, {"OUTAGE_RUNTIME_TEST_PROFILE": "nonsecret.json"})


@pytest.mark.parametrize("expression", ["runtime_docker", "runtime_measurements"])
def test_explicit_selection_requires_profile(expression):
    assert not opted_in(expression, {})
    assert opted_in(expression, {"OUTAGE_RUNTIME_TEST_PROFILE": "nonsecret.json"})


def test_default_acceptance_fixture_skips_before_any_process(monkeypatch):
    from tests.acceptance.test_query_runtime import harness

    monkeypatch.setenv("OUTAGE_RUNTIME_TEST_PROFILE", "/credentials/never-read")
    constructor = Mock(side_effect=AssertionError("must remain inert"))
    monkeypatch.setattr(
        "tests.acceptance.test_query_runtime.RuntimeHarness", constructor
    )
    request = SimpleNamespace(
        config=SimpleNamespace(option=SimpleNamespace(markexpr=""))
    )
    with pytest.raises(pytest.skip.Exception):
        next(harness.__wrapped__(request))
    constructor.assert_not_called()


def test_marker_without_configuration_skips_before_any_process(monkeypatch):
    from tests.acceptance.test_query_runtime import harness

    monkeypatch.delenv("OUTAGE_RUNTIME_TEST_PROFILE", raising=False)
    constructor = Mock(side_effect=AssertionError("must remain inert"))
    monkeypatch.setattr(
        "tests.acceptance.test_query_runtime.RuntimeHarness", constructor
    )
    request = SimpleNamespace(
        config=SimpleNamespace(option=SimpleNamespace(markexpr="runtime_docker"))
    )
    with pytest.raises(pytest.skip.Exception):
        next(harness.__wrapped__(request))
    constructor.assert_not_called()


def test_evidence_rejects_raw_secret_output_and_is_bounded(profile, tmp_path):
    report = EvidenceReport(profile)
    with pytest.raises(ValueError):
        report.gate("canary", "failed", {"stderr": "FAKE-CREDENTIAL-VALUE"})
    with pytest.raises(ValueError):
        report.gate("canary", "failed", {"seconds": float("nan")})
    report.gate("canary", "failed", {"seconds": 1.25, "bytes": 42})
    destination = tmp_path / "reports" / "evidence.json"
    digest = report.write(destination)
    assert len(digest) == 64
    raw = destination.read_bytes()
    assert len(raw) < 65536 and b"FAKE-CREDENTIAL" not in raw
    assert destination.stat().st_mode & 0o777 == 0o600
    assert json.loads(raw)["readiness"] == "unreviewed"
    with pytest.raises(FileExistsError):
        report.write(destination)


def test_failed_test_records_failed_gate_without_exception_text(profile):
    adapter = SimpleNamespace(report=EvidenceReport(profile))

    @record_gate
    def test_fake(*, harness):
        raise ValueError("FAKE-CREDENTIAL-DO-NOT-LOG")

    with pytest.raises(ValueError):
        test_fake(harness=adapter)
    raw = json.dumps(adapter.report.document)
    assert "FAKE-CREDENTIAL" not in raw
    assert adapter.report.document["gates"]["fake"]["status"] == "failed"


def test_profile_construction_is_inert_and_identity_failure_has_no_inspection_env(
    profile, tmp_path, monkeypatch
):
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps({"profile": asdict(profile), "evidence": None}))
    controller = Mock()
    monkeypatch.setattr("tests.runtime_validation.BoundedDockerControl", controller)
    adapter = RuntimeHarness(path, Path(__file__).absolute())
    controller.return_value.run.assert_not_called()
    controller.return_value.run.return_value = ControlResult(1, b"", b"FAKE_SECRET")
    with pytest.raises(ValueError, match="Daemon identity"):
        adapter.open()
    assert not Path(profile.staging_root).exists()
    args = controller.return_value.run.call_args.args[0]
    assert args == (
        "version",
        "--format",
        "{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}",
    )
    assert "Env" not in str(args)


def test_failed_cleanup_preserves_ownership(profile, tmp_path, monkeypatch):
    profile = replace(profile, docker_executable=str(Path(__file__).absolute()))
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps({"profile": asdict(profile), "evidence": None}))
    adapter = RuntimeHarness(path, Path(__file__).absolute())
    adapter.ledger.open()
    adapter._opened = True
    adapter.ledger.intend(str(tmp_path / "execution-canary"))
    monkeypatch.setattr(
        adapter.runtime,
        "terminate_and_reap",
        Mock(side_effect=RuntimeUnavailableError("fake")),
    )
    try:
        with pytest.raises(RuntimeUnavailableError):
            adapter.close()
        assert adapter.ledger.read() is not None
        assert adapter.ledger.root.exists()
    finally:
        adapter.ledger.clear()
        adapter.ledger.close()


def test_private_report_root_rejects_symlinks_and_public_permissions(tmp_path):
    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(ValueError):
        private_directory(public)
    link = tmp_path / "link"
    link.symlink_to(public, target_is_directory=True)
    with pytest.raises(ValueError):
        private_directory(link)


@pytest.mark.parametrize("bad", ["unknown", "duplicate", "pid", "too_big", "symlink"])
def test_representative_input_manifest_fails_closed(profile, tmp_path, bad):
    path = tmp_path / "inputs.json"
    values = {
        "old": {},
        "current": {},
        "refresh_pid": 3,
        "api_port": 8000,
        "api_pid": 4,
    }
    if bad == "unknown":
        values["credential"] = "FAKE"
    elif bad == "pid":
        values["refresh_pid"] = 1
    path.write_text(json.dumps(values))
    if bad == "duplicate":
        path.write_text('{"old":{},"old":{}}')
    elif bad == "too_big":
        path.write_bytes(b" " * 65537)
    elif bad == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    with pytest.raises(ValueError):
        read_representative_inputs(path, profile)


def test_measurements_retain_snapshots_encode_spool_page_without_source_work(
    profile, tmp_path, monkeypatch
):
    import hashlib

    from outage_explorer.application.ports.analytical_inputs import ApprovedFile
    from outage_explorer.domain.datasets import PUBLIC_DATASETS
    from outage_explorer.infrastructure.query_results.store import BoundedQueryResults

    for root in (profile.cache_root, profile.result_root, profile.staging_root):
        private_directory(Path(root))
    relations = []
    for dataset in PUBLIC_DATASETS:
        path = tmp_path / (dataset.id + ".public")
        path.write_bytes(dataset.id.encode())
        approved = ApprovedFile(
            str(path),
            hashlib.sha256(path.read_bytes()).hexdigest(),
            path.stat().st_size,
            1,
        )
        relations.append((dataset, (approved,)))
    inputs = RepresentativeInputs(
        "a" * 64, tuple(relations), tuple(relations), 3, 8000, 4
    )
    output = retain_result(
        (Column("n", ValueType("integer")),), [(42,)], profile.encoding_bounds
    )
    from outage_explorer.application.ports.query_results import QueryOutput

    queries = Mock(return_value=(QueryOutput(output.document, 1, None), 0.01))
    adapter = SimpleNamespace(profile=profile, query=queries)
    sampler = Mock()
    sampler.metrics = {"samples": 1, "spool_index_peak_bytes": 0}
    monkeypatch.setattr(
        "tests.runtime_validation.OverlapSampler", Mock(return_value=sampler)
    )
    page = BoundedQueryResults.acquire
    pages = []

    def acquire(store, identity, owner):
        pages.append(identity)
        return page(store, identity, owner)

    monkeypatch.setattr(BoundedQueryResults, "acquire", acquire)
    metrics = measured_workload(adapter, inputs)
    assert queries.call_count == 6  # aggregate + output; paging adds no execution
    assert len(pages) == 3
    expected = sum(f.byte_count for _, files in relations for f in files)
    assert metrics["local_copy_bytes"] == expected
    assert (
        metrics["warm_cumulative_local_copy_bytes"]
        == metrics["cold_cumulative_local_copy_bytes"]
    )
    assert metrics["old_and_current_retained_bytes"] == expected
    assert metrics["spool_index_peak_bytes"] > 0
    assert not list(Path(profile.cache_root).iterdir())
    assert not list(Path(profile.result_root).iterdir())
    sampler.start.assert_called_once()
    sampler.close.assert_called_once()


@pytest.mark.parametrize("fault", ["digest", "size", "deadline", "symlink"])
def test_copy_budget_mutation_or_symlink_leaves_no_cached_input(tmp_path, fault):
    import hashlib
    from time import monotonic

    from outage_explorer.application.ports.analytical_inputs import ApprovedFile
    from tests.runtime_validation import copy_verified

    source = tmp_path / "source"
    source.write_bytes(b"public")
    approved = ApprovedFile(str(source), hashlib.sha256(b"public").hexdigest(), 6, 1)
    if fault == "digest":
        source.write_bytes(b"mutate")
    elif fault == "size":
        source.write_bytes(b"oversized")
    elif fault == "symlink":
        link = tmp_path / "link"
        link.symlink_to(source)
        approved = ApprovedFile(str(link), approved.sha256, 6, 1)
    target = tmp_path / "copy"
    deadline = monotonic() - 1 if fault == "deadline" else monotonic() + 1
    with pytest.raises((ValueError, OSError)):
        copy_verified(approved, target, deadline)
    assert not target.exists()


def test_sampler_prerequisite_failure_creates_no_cache_or_spools(profile, monkeypatch):
    constructor = Mock(side_effect=ValueError("No already running workload"))
    monkeypatch.setattr("tests.runtime_validation.OverlapSampler", constructor)
    adapter = SimpleNamespace(profile=profile)
    with pytest.raises(ValueError):
        measured_workload(adapter, SimpleNamespace())
    assert not Path(profile.cache_root).exists()
    assert not Path(profile.result_root).exists()
