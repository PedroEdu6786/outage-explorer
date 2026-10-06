"""Controlled composition only: no real Docker, AWS or runtime-readiness claim."""

import json
import os
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.bootstrap import build_analytical_resources
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.entrypoints.http.analytical_command import run
from outage_explorer.infrastructure.query_results.previews import (
    BoundedPreviewSequences,
    PreviewBounds,
)
from outage_explorer.infrastructure.query_results.store import (
    BoundedQueryResults,
    ResultBounds,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    RuntimeEvidence,
    RuntimeProfile,
    read_runtime_config,
)
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from outage_explorer.infrastructure.worker_runtime.ownership import (
    OwnershipLedger,
    RecoveryOwner,
)
from outage_explorer.infrastructure.worker_runtime.supervisor import (
    AnalyticalResources,
    AnalyticalSupervisor,
)
from tests.integration.test_catalog_preview import Clock


def profile(tmp_path):
    return RuntimeProfile(
        image_id="sha256:" + "a" * 64,
        daemon_endpoint="unix:///var/run/docker.sock",
        platform="controlled-fixture",
        daemon_version="synthetic",
        filesystem_identity="fixture",
        temporary_backend="quota-disk",
        staging_root=str(tmp_path / "staging"),
        cache_root=str(tmp_path / "cache"),
        result_root=str(tmp_path / "results"),
        cleanup_interval_seconds=1,
    )


def evidence(candidate):
    # Matching fixture records are never proof of production readiness.
    return RuntimeEvidence(
        candidate.identity,
        *("b" * 64 for _ in range(5)),
        "controlled test fixture",
        date(2026, 10, 5),
    )


@pytest.fixture
def composed(tmp_path):
    candidate = profile(tmp_path)
    clock = Clock()
    runtime = Mock()
    resources = []
    order = []

    def construct(ledger, key):
        order.append("construct")
        recovery = RecoveryOwner()
        results = BoundedQueryResults(
            Path(candidate.result_root),
            clock,
            ResultBounds(3, 10, 12 * 1024**2, 131072),
        )
        sequences = BoundedPreviewSequences(
            clock, PreviewBounds(3, 10, 12 * 1024**2, 4096), key
        )
        result = AnalyticalResources(
            Mock(),
            VerifiedLauncher(
                candidate.execution_bounds,
                runtime,
                evidence="controlled only",
                recovery=recovery,
            ),
            results,
            sequences,
            recovery,
            runtime.terminate_and_reap,
            runtime.cancel,
            Mock(),
        )
        resources.append(result)
        return result

    supervisor = AnalyticalSupervisor(
        candidate,
        evidence(candidate),
        construct,
        lambda ledger: order.append("reconcile"),
    )
    yield supervisor, resources, clock, runtime, order
    if resources and supervisor._resources is not None:
        supervisor.close()


def test_inert_construction_start_idempotence_and_order(composed, tmp_path):
    supervisor, resources, _, _, order = composed
    assert not list(tmp_path.iterdir())
    with pytest.raises(RuntimeUnavailableError):
        supervisor.execution.reserve()
    assert resources == []
    supervisor.start()
    supervisor.start()
    assert order == ["reconcile", "construct"]
    reservation = supervisor.execution.reserve()
    reservation.close()
    supervisor.close()
    supervisor.close()
    assert not resources[0].results._records
    assert resources[0].close_inputs.call_count == 1
    with pytest.raises(RuntimeUnavailableError):
        supervisor.execution.reserve()


@pytest.mark.parametrize("mode", [{"serving_processes": 2}, {"reloader": True}])
def test_unsupported_modes_before_io(composed, tmp_path, mode):
    supervisor, resources, _, _, _ = composed
    with pytest.raises(RuntimeUnavailableError):
        supervisor.start(**mode)
    assert resources == []
    assert not list(tmp_path.iterdir())


def test_missing_stale_smoke_evidence_fails_before_io(tmp_path):
    candidate = profile(tmp_path)
    for record, selected in (
        (None, candidate),
        (evidence(candidate), replace(candidate, cpu_millicores=500)),
        (evidence(candidate), replace(candidate, temporary_backend="tmpfs-smoke")),
    ):
        construct, recover = Mock(), Mock()
        supervisor = AnalyticalSupervisor(selected, record, construct, recover)
        with pytest.raises(RuntimeUnavailableError):
            supervisor.start()
        construct.assert_not_called()
        recover.assert_not_called()
    assert not list(tmp_path.iterdir())


def test_rollback_releases_lock_and_only_owned_resources(composed):
    supervisor, resources, _, _, _ = composed
    supervisor._construct = Mock(
        side_effect=ValueError("controlled construction failure")
    )
    with pytest.raises(ValueError):
        supervisor.start()
    assert supervisor._ledger._fd is None
    assert resources == []
    supervisor.close()


def test_results_start_failure_rolls_back(composed, monkeypatch):
    supervisor, resources, _, _, _ = composed
    monkeypatch.setattr(
        BoundedQueryResults, "start", Mock(side_effect=ValueError("fixture"))
    )
    with pytest.raises(ValueError):
        supervisor.start()
    assert supervisor._ledger._fd is None
    assert resources[0].close_inputs.call_count == 1


def test_process_ownership_checked_before_start_and_close(composed, monkeypatch):
    supervisor, _, _, runtime, _ = composed
    supervisor.start()
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: supervisor._pid + 1)
        for operation in (
            supervisor.start,
            supervisor.close,
            supervisor.execution.reserve,
        ):
            with pytest.raises(RuntimeUnavailableError):
                operation()
    runtime.terminate_and_reap.assert_not_called()


def test_close_preserves_active_execution_then_retries(composed):
    supervisor, resources, _, _, _ = composed
    supervisor.start()
    reservation = supervisor.execution.reserve()
    with pytest.raises(RuntimeUnavailableError):
        supervisor.close()
    assert supervisor._ledger._fd is not None
    assert resources[0].close_inputs.call_count == 0
    with pytest.raises(RuntimeUnavailableError):
        supervisor.execution.reserve()
    reservation.close()
    supervisor.close()
    assert supervisor._ledger._fd is None


def test_preview_expiry_and_close_retain_active_lease(composed):
    supervisor, resources, clock, _, _ = composed
    supervisor.start()
    inputs = Mock(files=())
    sequence = resources[0].sequences.create(
        "caller", PUBLIC_DATASETS[0], Mock(), None, None, 2, inputs
    )
    clock.value += timedelta(minutes=16)
    supervisor.sweep()
    inputs.close.assert_not_called()
    with pytest.raises(RuntimeUnavailableError):
        supervisor.close()
    inputs.close.assert_not_called()
    supervisor.sequences.release(sequence)
    supervisor.close()
    inputs.close.assert_called_once()


def test_recovery_before_expiry_and_close_unresolved(composed):
    supervisor, resources, _, _, _ = composed
    supervisor.start()
    state = resources[0]
    reap = Mock(side_effect=RuntimeUnavailableError("unresolved fixture"))
    lease = Mock()
    state.recovery.retain(reap, (lease,))
    supervisor.sweep()
    lease.close.assert_not_called()
    with pytest.raises(RuntimeUnavailableError):
        supervisor.close()
    assert supervisor._ledger._fd is not None
    reap.side_effect = None
    supervisor.close()
    lease.close.assert_called_once()


def test_autonomous_sweep_without_request(composed):
    from threading import Event

    supervisor, resources, _, _, _ = composed
    supervisor.start()
    done = Event()
    resources[0].recovery.retain(lambda: None, (Mock(close=done.set),))
    assert done.wait(3)
    assert resources[0].recovery.pending == 0


def test_single_owner_lock_preserves_live_owner(composed):
    supervisor, _, _, _, _ = composed
    supervisor.start()
    second = OwnershipLedger(Path(supervisor.profile.staging_root), "c" * 32)
    with pytest.raises(RuntimeUnavailableError):
        second.open()
    assert second._fd is None


def test_production_builder_inert_and_quota_prerequisites_closed(tmp_path, monkeypatch):
    from outage_explorer.infrastructure.worker_runtime.docker import (
        BoundedDockerControl,
    )

    monkeypatch.setattr(
        BoundedDockerControl,
        "run",
        Mock(side_effect=RuntimeUnavailableError("controlled daemon unavailable")),
    )
    candidate = profile(tmp_path)
    resources = build_analytical_resources(candidate, evidence(candidate))
    assert not list(tmp_path.iterdir())
    with pytest.raises(RuntimeUnavailableError, match="daemon unavailable"):
        resources.start()
    resources.close()
    assert not Path(candidate.cache_root).exists()
    assert not Path(candidate.result_root).exists()


def test_config_round_trip_missing_evidence_and_strict_rejection(tmp_path):
    candidate = profile(tmp_path)
    record = asdict(evidence(candidate))
    record["reviewed_on"] = record["reviewed_on"].isoformat()
    path = tmp_path / "nonsecret.json"
    path.write_text(json.dumps({"profile": asdict(candidate), "evidence": record}))
    assert read_runtime_config(path) == (candidate, evidence(candidate))
    path.write_text(json.dumps({"profile": asdict(candidate), "evidence": None}))
    assert read_runtime_config(path) == (candidate, None)
    for raw in (
        '{"profile":{},"profile":{},"evidence":null}',
        '{"profile":{},"evidence":null,"secret":"fake"}',
        "x" * 65537,
    ):
        path.write_text(raw)
        with pytest.raises(ValueError):
            read_runtime_config(path)


def test_command_help_and_reloader_multi_mode_rejection():
    execute = Mock()
    with pytest.raises(SystemExit) as help_exit:
        run(execute, ["--help"])
    assert help_exit.value.code == 0
    execute.assert_not_called()
    for extra in (["--reload"], ["--workers", "2"], ["--host", "0.0.0.0"]):
        with pytest.raises(SystemExit) as error:
            run(execute, ["--config", "/private/tmp/nonsecret.json", *extra])
        assert error.value.code == 2
    execute.assert_not_called()


@pytest.mark.parametrize(
    "replacement",
    [None, True, 123, [], {}],
)
def test_malformed_daemon_configuration_is_sanitized(tmp_path, capsys, replacement):
    candidate = asdict(profile(tmp_path))
    candidate["daemon_endpoint"] = replacement
    path = tmp_path / "nonsecret.json"
    path.write_text(json.dumps({"profile": candidate, "evidence": None}))
    with pytest.raises(ValueError, match="Invalid nonsecret analytical runtime"):
        read_runtime_config(path)
    with pytest.raises(SystemExit) as error:
        run(
            lambda config, host, port: read_runtime_config(Path(config)),
            ["--config", str(path)],
        )
    assert error.value.code == 1
    assert capsys.readouterr().err == "Reviewed analytical runtime unavailable\n"


def test_deep_configuration_is_sanitized(tmp_path):
    path = tmp_path / "nonsecret.json"
    path.write_text("[" * 20000 + "0" + "]" * 20000)
    with pytest.raises(ValueError, match="Invalid nonsecret analytical runtime"):
        read_runtime_config(path)


def test_missing_evidence_explicit_startup_never_serves(tmp_path, monkeypatch):
    from outage_explorer import bootstrap

    path = tmp_path / "nonsecret.json"
    path.write_text(
        json.dumps({"profile": asdict(profile(tmp_path)), "evidence": None})
    )
    app = Mock()
    app.extensions = {"outage_data_close": Mock()}
    monkeypatch.setattr(bootstrap, "build_http_app", Mock(return_value=app))
    with pytest.raises(RuntimeUnavailableError):
        bootstrap.execute_analytical_http(str(path), "127.0.0.1", 5000)
    app.run.assert_not_called()
    app.extensions["outage_data_close"].assert_called_once()
    assert not (tmp_path / "staging").exists()
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "results").exists()


def test_dead_owner_recovery_precedes_cache_construction(tmp_path):
    from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
    from tests.unit.test_docker_runtime import OWNER, Control

    candidate = profile(tmp_path)
    old = OwnershipLedger(Path(candidate.staging_root), OWNER)
    old.open()
    stage = Path(candidate.staging_root) / "execution-orphan"
    stage.mkdir(mode=0o700)
    (stage / "input.parquet").write_bytes(b"controlled placeholder")
    old.intend(str(stage))
    old.close()
    control = Control()
    control.running = True
    order = []

    def recover(ledger):
        # This legacy record was created under the smoke backend. Native disk
        # recovery is separately exercised with its exact spill ownership.
        DockerRuntime(
            replace(candidate, temporary_backend="tmpfs-smoke"), control, ledger
        ).recover_owned()
        order.append("recovered")

    def construct(ledger, key):
        assert not stage.exists()
        assert ledger.read() is None
        order.append("construct")
        raise ValueError("controlled stop after proving recovery")

    supervisor = AnalyticalSupervisor(
        candidate, evidence(candidate), construct, recover
    )
    with pytest.raises(ValueError):
        supervisor.start()
    operations = [arguments[0] for arguments, _ in control.calls]
    assert operations == ["inspect", "kill", "wait", "inspect", "rm"]
    assert order == ["recovered", "construct"]
    assert supervisor._ledger._fd is None


def test_dead_owner_failed_reap_keeps_staging_and_no_construct(tmp_path):
    from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
    from tests.unit.test_docker_runtime import OWNER, Control

    candidate = profile(tmp_path)
    old = OwnershipLedger(Path(candidate.staging_root), OWNER)
    old.open()
    stage = Path(candidate.staging_root) / "execution-orphan"
    stage.mkdir(mode=0o700)
    old.intend(str(stage))
    old.close()
    control = Control()
    control.fail = "wait"
    construct = Mock()
    supervisor = AnalyticalSupervisor(
        candidate,
        evidence(candidate),
        construct,
        lambda ledger: DockerRuntime(candidate, control, ledger).recover_owned(),
    )
    with pytest.raises(RuntimeUnavailableError):
        supervisor.start()
    assert stage.exists()
    assert (Path(candidate.staging_root) / "worker.json").exists()
    construct.assert_not_called()


def test_private_cache_reclamation_only_known_bounded_owned_paths(tmp_path):
    from outage_explorer.infrastructure.local_cache.modeled import reclaim_private_cache

    root = tmp_path / "cache"
    root.mkdir(mode=0o700)
    known = root / ("a" * 64 + "-national-0.parquet")
    known.write_bytes(b"old modeled fixture")
    unknown = root / "durable-source"
    unknown.write_bytes(b"preserve fixture")
    with pytest.raises(ValueError, match="Unknown"):
        reclaim_private_cache(root, file_limit=10)
    assert known.exists() and unknown.exists()
    unknown.unlink()
    with pytest.raises(ValueError, match="limit"):
        reclaim_private_cache(root, file_limit=0)
    assert known.exists()
    reclaim_private_cache(root, file_limit=10)
    assert not list(root.iterdir())


def test_recovery_failure_preserves_cache_before_construct(tmp_path):
    from outage_explorer.infrastructure.local_cache.modeled import reclaim_private_cache

    candidate = profile(tmp_path)
    cache = Path(candidate.cache_root)
    cache.mkdir(mode=0o700)
    old_file = cache / ("a" * 64 + "-national-0.parquet")
    old_file.write_bytes(b"orphan fixture")
    construct = Mock(
        side_effect=lambda ledger, key: reclaim_private_cache(cache, file_limit=10)
    )
    recover = Mock(side_effect=RuntimeUnavailableError("death unconfirmed"))
    supervisor = AnalyticalSupervisor(
        candidate, evidence(candidate), construct, recover
    )
    with pytest.raises(RuntimeUnavailableError):
        supervisor.start()
    construct.assert_not_called()
    assert old_file.exists()
