from dataclasses import replace
from datetime import date

import pytest

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.bootstrap import build_query_worker
from outage_explorer.infrastructure.worker_runtime.configuration import (
    RuntimeEvidence,
    RuntimeProfile,
    WorkerImageLimits,
)
from outage_explorer.settings import AnalyticalWorkerSettings


def profile(**changes):
    return RuntimeProfile(
        image_id="sha256:" + "a" * 64,
        daemon_endpoint="unix:///var/run/docker.sock",
        platform="linux-amd64",
        daemon_version="candidate",
        filesystem_identity="synthetic",
        **changes,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"image_id": "worker:latest"},
        {"daemon_endpoint": "tcp://localhost:2375"},
        {"memory_bytes": 0},
        {"network": "host"},
        {"uid": 0},
        {"uid": True},
        {"mounts": ("/var/run/docker.sock",)},
        {"environment": (("AWS_SECRET", "fake"),)},
        {"read_only_root": False},
        {"no_new_privileges": False},
        {"serving_processes": 2},
        {"process_limit": True},
        {"control_seconds": float("inf")},
        {"cache_bytes": "1"},
        {"swap_bytes": 1},
        {"worker": WorkerImageLimits(memory_bytes=100)},
    ],
)
def test_invalid_configuration(changes):
    values = dict(
        image_id="sha256:" + "a" * 64,
        daemon_endpoint="unix:///var/run/docker.sock",
        platform="linux-amd64",
        daemon_version="candidate",
        filesystem_identity="synthetic",
    )
    values.update(changes)
    with pytest.raises((ValueError, TypeError)):
        RuntimeProfile(**values)


def test_readiness_and_invalidation():
    candidate = profile()
    reviewed = replace(candidate, temporary_backend="quota-disk")
    evidence = RuntimeEvidence(
        reviewed.identity,
        *("b" * 64 for _ in range(5)),
        "user review",
        date(2026, 10, 5),
    )
    evidence.require_ready(reviewed, started=True)
    for p, started in [
        (reviewed, False),
        (candidate, True),
        (replace(reviewed, process_limit=16), True),
        (replace(reviewed, image_id="sha256:" + "c" * 64), True),
    ]:
        with pytest.raises(RuntimeUnavailableError):
            evidence.require_ready(p, started=started)
    assert reviewed.execution_bounds.memory_bytes == reviewed.worker.memory_bytes
    assert reviewed.encoding_bounds.max_depth == reviewed.worker.max_depth


def test_worker_image_mismatch_rejected():
    with pytest.raises(ValueError):
        build_query_worker(settings=AnalyticalWorkerSettings(memory_bytes=100))


def test_worker_caps():
    with pytest.raises(ValueError):
        AnalyticalWorkerSettings(execution_seconds=11)
    with pytest.raises(ValueError):
        AnalyticalWorkerSettings(output_bytes=1_048_577)


def test_settings_and_adapter_image_limits_match():
    from dataclasses import asdict

    assert asdict(AnalyticalWorkerSettings()) == asdict(WorkerImageLimits())


@pytest.mark.parametrize(
    "changes",
    [
        {"staging_root": "/"},
        {"cache_root": "/tmp/outage-analytical/staging/child"},
        {"result_lifetime_seconds": 901},
        {"preview_lifetime_seconds": True},
    ],
)
def test_private_roots_and_fixed_lifetimes(changes):
    with pytest.raises(ValueError):
        profile(**changes)
