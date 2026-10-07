"""Explicit three-resource composition with a controlled SDK; never AWS/EIA."""

import threading
from dataclasses import replace

import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    TransferBounds,
)
from outage_explorer.application.services.resource_artifacts import (
    PersistResourceArtifacts,
    RecoverResourceArtifacts,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.s3.resources import S3ResourceStore
from tests.integration.test_connector_parquet import ARTIFACT_BOUNDS, BOUNDS
from tests.integration.test_resource_candidates import build
from tests.integration.test_s3_artifacts import ControlledS3, failure


def composition(store, client, count=3, **kwargs):
    cancelled = threading.Event()
    workers = BoundedConnectorWorkers(count, cancelled)
    local = LocalConnectorEvidence(store, workers)
    remote = S3ResourceStore(
        client,
        "test-bucket",
        "connector/",
        ARTIFACT_BOUNDS,
        cancelled=cancelled,
        **kwargs,
    )
    return local, remote, workers


@pytest.mark.parametrize("count", [1, 2, 3])
def test_exact_three_put_get_receipt_and_recovery(tmp_path, count):
    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    prior = build(store, generation="generation_1")
    candidate = build(store, generation="generation_2", prior=prior.baseline)
    client = ControlledS3()
    local, remote, workers = composition(store, client, count)
    receipt = PersistResourceArtifacts(local, remote, workers).execute(
        candidate, BOUNDS
    )
    expected = {
        "connector/generations/generation_2/" + name + ".parquet"
        for name in ("national", "facilities", "generators")
    }
    assert set(client.objects) == expected
    assert len(client.calls) == 6
    assert sum(kind == "get" for kind, _ in client.calls) == 3
    assert receipt.interval == candidate.interval
    assert receipt.base_generation_id == "generation_1"
    assert receipt.contract_id == candidate.contract_id
    assert receipt.transformation_id == candidate.transformation_id
    target = LocalParquetStore(tmp_path / "recovered", ARTIFACT_BOUNDS)
    restored, reader, _ = composition(target, client, count)
    baseline = RecoverResourceArtifacts(restored, reader).execute(receipt, BOUNDS)
    assert baseline == candidate.baseline
    assert len(client.calls) == 9
    assert len(list(target.root.iterdir())) == 3
    assert all(body.closed for body in client.closed_bodies)
    # Existing identical keys require exactly three conditional PUT + GET pairs.
    _, retry, retry_workers = composition(store, client, count)
    assert (
        PersistResourceArtifacts(local, retry, retry_workers).execute(candidate, BOUNDS)
        == receipt
    )
    assert len(client.calls) == 15


@pytest.mark.parametrize(
    "generation", ["../bad", "a/b", "", "a?b", "a\\b", "a\nb", "x" * 1024]
)
def test_unsafe_generation_rejected_before_sdk(tmp_path, generation):
    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    candidate = build(store)
    client = ControlledS3()
    local, remote, workers = composition(store, client)
    with pytest.raises(ArtifactError):
        PersistResourceArtifacts(local, remote, workers).execute(
            replace(candidate, generation_id=generation), BOUNDS
        )
    assert client.calls == []


def saved(tmp_path):
    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    candidate = build(store)
    client = ControlledS3()
    local, remote, workers = composition(store, client)
    receipt = PersistResourceArtifacts(local, remote, workers).execute(
        candidate, BOUNDS
    )
    return store, candidate, client, receipt


@pytest.mark.parametrize("mutation", ["generation", "grain", "key", "hash", "rows"])
def test_receipt_rejects_wrong_identity_before_sdk(tmp_path, mutation):
    _, _, client, receipt = saved(tmp_path)
    if mutation == "generation":
        receipt = replace(receipt, generation_id="other")
    else:
        ref = receipt.resources[0]
        if mutation == "grain":
            ref = replace(
                ref,
                object=replace(
                    ref.object,
                    key=ref.object.key.replace(
                        "candidate/national.parquet", "other/facilities.parquet"
                    ),
                ),
            )
        elif mutation == "key":
            ref = replace(
                ref, object=replace(ref.object, key="elsewhere/national.parquet")
            )
        elif mutation == "hash":
            ref = replace(ref, object=replace(ref.object, sha256="not-a-hash"))
        elif mutation == "rows":
            with pytest.raises(ArtifactError):
                replace(
                    receipt,
                    resources=(replace(ref, row_count=0), *receipt.resources[1:]),
                )
            return
        receipt = replace(receipt, resources=(ref, *receipt.resources[1:]))
    target = LocalParquetStore(tmp_path / "target", ARTIFACT_BOUNDS)
    local, remote, _ = composition(target, client)
    before = len(client.calls)
    with pytest.raises(ArtifactError):
        RecoverResourceArtifacts(local, remote).execute(receipt, BOUNDS)
    assert len(client.calls) == before
    assert list(target.root.iterdir()) == []


@pytest.mark.parametrize("fault", ["corrupt", "short", "rows", "schema"])
def test_recovery_failure_cleans_new_files_preserves_existing(tmp_path, fault):
    store, candidate, client, receipt = saved(tmp_path)
    target = LocalParquetStore(tmp_path / "target", ARTIFACT_BOUNDS)
    existing = candidate.resources[-1]
    target.put_immutable(store.read(existing.object))
    keep = target._path(existing.object).read_bytes()
    if fault == "corrupt":
        client.read_transform = lambda key, data: b"x" + data[1:]
    elif fault == "short":
        client.read_transform = lambda key, data: data[:-1]
    elif fault == "rows":
        receipt = replace(
            receipt,
            resources=(
                replace(receipt.resources[0], row_count=99),
                *receipt.resources[1:],
            ),
        )
    else:
        # A byte-valid non-resource Parquet file must fail physical schema checks.
        wrong = store.write_file(
            "public",
            "national",
            [
                {
                    column.name: record[column.name]
                    for column in PUBLIC_DATASETS[0].columns
                }
                for record in store.records(candidate.resources[0])
            ],
        )
        data = b"".join(store.read(wrong.object))
        remote = receipt.resources[0]
        client.objects[remote.object.key] = data
        receipt = replace(
            receipt,
            resources=(
                replace(
                    remote,
                    object=replace(
                        remote.object,
                        sha256=wrong.object.sha256,
                        byte_count=wrong.object.byte_count,
                    ),
                    row_count=wrong.row_count,
                ),
                *receipt.resources[1:],
            ),
        )
    local, remote, _ = composition(target, client)
    with pytest.raises(ArtifactError):
        RecoverResourceArtifacts(local, remote).execute(receipt, BOUNDS)
    assert list(target.root.iterdir()) == [target._path(existing.object)]
    assert target._path(existing.object).read_bytes() == keep
    assert all(body.closed for body in client.closed_bodies)
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())


@pytest.mark.parametrize("cap", ["requests", "wire_bytes", "temporary_bytes"])
def test_shared_transfer_caps_no_receipt(tmp_path, cap):
    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    candidate = build(store)
    client = ControlledS3()
    local, remote, workers = composition(
        store, client, transfer=replace(TransferBounds(), **{cap: 1})
    )
    with pytest.raises(ArtifactLimitError):
        PersistResourceArtifacts(local, remote, workers).execute(candidate, BOUNDS)
    assert remote.temporary_bytes == 0
    assert all(body.closed for body in client.closed_bodies)
    assert len(list(store.root.iterdir())) == 3


def test_retry_and_conflicting_existing_bytes_fail_closed(tmp_path):
    store, candidate, client, receipt = saved(tmp_path)
    client.put_faults = [failure("ConditionalRequestConflict")]
    local, remote, workers = composition(store, client, count=1)
    assert (
        PersistResourceArtifacts(local, remote, workers).execute(candidate, BOUNDS)
        == receipt
    )
    key = receipt.resources[0].object.key
    client.objects[key] = b"x" + client.objects[key][1:]
    snapshot = dict(client.objects)
    local, remote, workers = composition(store, client, count=1)
    with pytest.raises(ArtifactError):
        PersistResourceArtifacts(local, remote, workers).execute(candidate, BOUNDS)
    assert client.objects == snapshot
    assert all(body.closed for body in client.closed_bodies)


@pytest.mark.parametrize("count", [2, 3])
def test_exact_resource_transfers_overlap_within_worker_limit(tmp_path, count):
    class BarrierS3(ControlledS3):
        def __init__(self):
            super().__init__()
            self.lock = threading.RLock()
            self.barriers = {
                kind: threading.Barrier(count, timeout=5) for kind in ("put", "get")
            }
            self.started = {"put": 0, "get": 0}
            self.active = self.peak = 0

        def operation(self, kind, kwargs):
            with self.lock:
                index = self.started[kind]
                self.started[kind] += 1
                self.active += 1
                self.peak = max(self.peak, self.active)
            try:
                if index < count:
                    self.barriers[kind].wait()
                with self.lock:
                    return getattr(super(), kind + "_object")(**kwargs)
            finally:
                with self.lock:
                    self.active -= 1

        def put_object(self, **kwargs):
            return self.operation("put", kwargs)

        def get_object(self, **kwargs):
            return self.operation("get", kwargs)

    store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
    candidate = build(store)
    client = BarrierS3()
    local, remote, workers = composition(store, client, count)
    PersistResourceArtifacts(local, remote, workers).execute(candidate, BOUNDS)
    assert client.peak == count
    assert client.active == 0
    assert len(client.calls) == 6
    assert all(body.closed for body in client.closed_bodies)


def test_recovery_staging_reserves_all_missing_bytes_before_sdk(tmp_path):
    _, _, client, receipt = saved(tmp_path)
    size = sum(ref.object.byte_count for ref in receipt.resources)
    target = LocalParquetStore(tmp_path / "target", ARTIFACT_BOUNDS)
    local, remote, _ = composition(
        target, client, transfer=replace(TransferBounds(), temporary_bytes=size - 1)
    )
    before = list(client.calls)
    with pytest.raises(ArtifactLimitError):
        RecoverResourceArtifacts(local, remote).execute(receipt, BOUNDS)
    assert client.calls == before
    assert list(target.root.iterdir()) == []
    assert remote.temporary_bytes == 0


def test_cancelled_store_cleanup_after_join_preserves_preexisting(
    tmp_path, monkeypatch
):
    store, candidate, client, receipt = saved(tmp_path)
    target = LocalParquetStore(tmp_path / "target", ARTIFACT_BOUNDS)
    existing = candidate.resources[-1]
    target.put_immutable(store.read(existing.object))
    local, remote, workers = composition(target, client)
    target.check = workers.check

    def cancelled_validation(*args):
        assert not any(t.name.startswith("connector_") for t in threading.enumerate())
        assert all(body.closed for body in client.closed_bodies)
        workers.cancelled.set()
        workers.check()

    monkeypatch.setattr(local, "verify_baseline", cancelled_validation)
    with pytest.raises(ArtifactLimitError):
        RecoverResourceArtifacts(local, remote).execute(receipt, BOUNDS)
    assert list(target.root.iterdir()) == [target.root / existing.object.key]
    assert target._bytes == existing.object.byte_count
    assert remote.temporary_bytes == 0


def test_faulty_transfer_port_cannot_commit_unexpected_digest(tmp_path):
    _, _, client, receipt = saved(tmp_path)
    target = LocalParquetStore(tmp_path / "target", ARTIFACT_BOUNDS)
    local, remote, _ = composition(target, client, count=1)

    class FaultyTransfer:
        validate_receipt = remote.validate_receipt
        recovery_staging = remote.recovery_staging

        def read(self, reference):
            yield b"incorrect bytes from a faulty port"

    with pytest.raises(ArtifactError, match="expected exact identity"):
        local.restore_resources(receipt, FaultyTransfer(), BOUNDS)
    assert list(target.root.iterdir()) == []
    assert target._bytes == 0
    assert remote.temporary_bytes == 0
