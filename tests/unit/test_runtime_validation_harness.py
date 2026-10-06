"""Controlled validation-harness checks; never invoke Docker or source services."""

import hashlib
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
    MEASUREMENT_MANIFEST_BYTES,
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
        path.write_bytes(b" " * (MEASUREMENT_MANIFEST_BYTES + 1))
    elif bad == "symlink":
        link = tmp_path / "link"
        link.symlink_to(path)
        path = link
    with pytest.raises(ValueError):
        read_representative_inputs(path, profile)


def test_initial_interval_partition_manifest_and_independent_limits(profile, tmp_path):
    from datetime import date
    from decimal import Decimal

    import pyarrow as pa
    import pyarrow.parquet as pq

    from outage_explorer.domain.datasets import PUBLIC_DATASETS
    from outage_explorer.infrastructure.parquet.schemas import schema_for

    snapshot = {}
    total_bytes = 0
    for dataset in PUBLIC_DATASETS:
        schema = schema_for("modeled", dataset.grain)
        public_schema = pa.schema([schema.field(c.name) for c in dataset.columns])
        path = tmp_path / (dataset.id + ".parquet")
        pq.write_table(
            pa.Table.from_pylist(
                [
                    {
                        c.name: date(2026, 4, 2)
                        if c.name == "period"
                        else Decimal(1)
                        if c.value_type.kind == "decimal"
                        else "public"
                        for c in dataset.columns
                    }
                ],
                schema=public_schema,
            ),
            path,
        )
        descriptor = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "byte_count": path.stat().st_size,
            "rows": 1,
        }
        snapshot[dataset.id] = [descriptor] * 183
        total_bytes += descriptor["byte_count"] * 183 * 2
    path = tmp_path / "partitioned.json"
    path.write_text(
        json.dumps(
            {
                "old": snapshot,
                "current": snapshot,
                "refresh_pid": 3,
                "api_pid": 4,
                "api_port": 8000,
            }
        )
    )
    assert 65_536 < path.stat().st_size < MEASUREMENT_MANIFEST_BYTES
    inputs = read_representative_inputs(path, profile)
    assert sum(len(files) for _, files in inputs.old + inputs.current) == 1098
    for limited in (
        replace(profile, input_files=1097),
        replace(profile, cache_bytes=total_bytes - 1),
    ):
        with pytest.raises(ValueError, match="input budget exceeded"):
            read_representative_inputs(path, limited)
    document = json.loads(path.read_text())
    with pytest.raises(ValueError, match="Invalid representative manifest"):
        read_representative_inputs(path, profile, analytical_only=True)
    partial = {k: document[k] for k in ("old", "current")}
    path.write_text(json.dumps(partial))
    assert (
        read_representative_inputs(path, profile, analytical_only=True).api_pid is None
    )
    with pytest.raises(ValueError, match="Invalid representative manifest"):
        read_representative_inputs(path, profile)
    path.write_text('{"old":{},"old":{},"current":{}}')
    with pytest.raises(ValueError, match="Duplicate representative key"):
        read_representative_inputs(path, profile, analytical_only=True)
    path.write_text(json.dumps({**partial, "unknown": 1}))
    with pytest.raises(ValueError, match="Invalid representative manifest"):
        read_representative_inputs(path, profile, analytical_only=True)


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


@pytest.mark.parametrize(
    "fault,stage",
    [
        ("host", "host_memory"),
        ("disk", "filesystem"),
        ("control", "container_control"),
        ("decode", "container_decode"),
        (None, None),
    ],
)
def test_sampler_records_only_bounded_failure_stage_counters(
    profile, monkeypatch, fault, stage
):
    from tests.runtime_validation import OverlapSampler

    original = Path
    memory = Mock()
    memory.is_file.return_value = fault != "host"
    memory.read_text.return_value = "MemAvailable: 4096 kB\n"
    monkeypatch.setattr(
        "tests.runtime_validation.Path",
        lambda p: memory if str(p) == "/proc/meminfo" else original(p),
    )
    sizes = Mock(return_value=1)
    if fault == "disk":
        sizes.side_effect = OSError("private-path-canary")
    monkeypatch.setattr("tests.runtime_validation.directory_bytes", sizes)
    command = Mock(
        return_value=SimpleNamespace(code=0, stdout=b"94MiB / 512MiB|100.0%")
    )
    if fault == "control":
        command.side_effect = RuntimeError("private-diagnostic-canary")
    elif fault == "decode":
        command.return_value.stdout = b"private-invalid-output-canary"
    sampler = OverlapSampler(
        SimpleNamespace(
            profile=profile,
            runtime=SimpleNamespace(_container="owned-test"),
            command=command,
        ),
        None,
    )
    sampler.stop = Mock()
    sampler.stop.is_set.side_effect = [False, True]
    sampler._sample()
    assert sampler.metrics["samples"] == int(fault is None)
    assert sampler.metrics["sampling_failures"] == int(fault is not None)
    counters = {
        key: value
        for key, value in sampler.metrics.items()
        if key.startswith("sampling_") and key != "sampling_failures"
    }
    assert sum(counters.values()) == sampler.metrics["sampling_failures"]
    if stage:
        assert counters["sampling_" + stage + "_failures"] == 1
    assert all(type(value) in (int, float) for value in sampler.metrics.values())
    assert "canary" not in json.dumps(sampler.metrics)


@pytest.mark.parametrize(
    "fault", [None, "order", "overlap", "filter", "size", "projection"]
)
def test_representative_preview_calls_validate_projection_keys_and_date_range(
    profile, fault
):
    from datetime import date, timedelta
    from decimal import Decimal

    from outage_explorer.application.errors import AnalyticalResourceError
    from outage_explorer.application.ports.execution import PreviewRows
    from outage_explorer.domain.datasets import PUBLIC_DATASETS
    from tests.runtime_validation import measure_previews

    def preview(request):
        if request.start is not None:
            days = [date(2026, 10, 2)]
            if fault == "filter":
                days = [date(2026, 4, 2)]
        elif request.after is not None:
            days = [date.fromisoformat(request.after[0]) - timedelta(days=1)]
            if fault == "overlap":
                days = [date.fromisoformat(request.after[0])]
        else:
            count = 101 if fault == "size" else 100
            days = [date(2026, 10, 1) - timedelta(days=i) for i in range(count)]
            if fault == "order":
                days.reverse()
        rows = []
        for day in days:
            values = []
            for col in request.dataset.columns:
                values.append(
                    day
                    if col.value_type.kind == "date"
                    else Decimal("1")
                    if col.value_type.kind == "decimal"
                    else "value"
                )
            rows.append(tuple(values[:-1] if fault == "projection" else values))
        return PreviewRows(
            tuple(rows),
            tuple((day.isoformat(),) for day in days),
            request.after is None and request.start is None,
        ), 0.01

    calls = Mock(side_effect=preview)
    harness = SimpleNamespace(profile=profile, preview=calls)
    metrics = {}
    if fault is not None:
        with pytest.raises((ValueError, AnalyticalResourceError)):
            measure_previews(harness, [(PUBLIC_DATASETS[0], ())], "old", metrics)
    else:
        for label in ("old", "cold", "warm"):
            measure_previews(
                harness, [(d, ()) for d in PUBLIC_DATASETS], label, metrics
            )
        assert calls.call_count == 27
        assert len(metrics) == 54
        assert metrics["warm_generators_filtered_rows"] == 1
        report = EvidenceReport(profile)
        report.gate("preview_workload", "passed", metrics)
        assert len(report.document["gates"]["preview_workload"]["metrics"]) == 54
        assert "2026-10" not in json.dumps(metrics)
