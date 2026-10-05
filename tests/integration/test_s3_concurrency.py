"""Bounded overlapping SDK operations and exact graph replay, without AWS."""

import threading
from dataclasses import replace

import pytest

from outage_explorer.application.dto import ConnectorArtifactInput
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    TransferBounds,
)
from outage_explorer.application.services.connector_artifacts import (
    PersistConnectorArtifacts,
)
from outage_explorer.bootstrap import execute_connector_artifacts
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from tests.integration.test_connector_artifacts import ENV, candidate
from tests.integration.test_connector_cli import MODEL, config_file, reopen
from tests.integration.test_s3_artifacts import (
    ControlledS3,
    adapter,
    failure,
    reference,
)


class OverlappingS3(ControlledS3):
    def __init__(self, *, fault=None):
        super().__init__()
        self.lock = threading.RLock()
        self.put_barrier = threading.Barrier(3, timeout=5)
        self.get_barrier = threading.Barrier(3, timeout=5)
        self.put_started = self.get_started = 0
        self.active = self.peak = 0
        self.fault = fault
        self.failed = False
        self.third_put = threading.Event()
        self.put_completions = []

    def operation(self, kind, kwargs):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            count = getattr(self, kind + "_started")
            setattr(self, kind + "_started", count + 1)
        try:
            # The first three dependencies must reach PUT and readback together.
            if count < 3:
                getattr(self, kind + "_barrier").wait()
            if kind == "put" and count == 0 and not self.fault:
                assert self.third_put.wait(5)
            with self.lock:
                if kind == "put" and self.fault and not self.failed:
                    self.failed = True
                    if self.fault == "interrupt":
                        raise KeyboardInterrupt
                    raise failure("AccessDenied")
                result = getattr(super(), kind + "_object")(**kwargs)
                if kind == "put":
                    self.put_completions.append(count)
                    if count == 2:
                        self.third_put.set()
                return result
        finally:
            with self.lock:
                self.active -= 1

    def put_object(self, **kwargs):
        return self.operation("put", kwargs)

    def get_object(self, **kwargs):
        return self.operation("get", kwargs)


def transfer(client, root, ref, operation="persist"):
    return execute_connector_artifacts(
        ConnectorArtifactInput(
            operation,
            str(root),
            f"{ref.key}:{ref.byte_count}",
            config_file(root, {"workers": {"s3_workers": 3}}),
        ),
        environment=ENV,
        client=client,
    )


def clean(client):
    assert client.active == 0
    assert all(body.closed for body in client.closed_bodies)
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())


def test_parallel_put_and_get_exact_inherited_graph_and_receipts(tmp_path):
    root = tmp_path / "original"
    first = candidate(root)
    ref = candidate(root, first, outage="invalid")
    store, original = reopen(root, ref)
    graph = LocalConnectorEvidence(store).graph(ref, MODEL)
    concurrent = OverlappingS3()
    receipt = transfer(concurrent, root, ref)
    clean(concurrent)
    assert concurrent.peak == 3
    assert concurrent.put_completions.index(2) < concurrent.put_completions.index(0)
    assert [key for kind, key in concurrent.calls if kind == "put"][-1].endswith(
        ref.key
    )
    assert receipt.objects == len(graph)
    from tests.integration.test_connector_artifacts import (
        transfer as sequential_transfer,
    )

    assert sequential_transfer(concurrent, root, ref) == receipt
    # Conditional identical retries are verified with bytes, never overwritten.
    snapshot = dict(concurrent.objects)
    assert transfer(concurrent, root, ref) == receipt
    assert concurrent.objects == snapshot
    recovered = tmp_path / "recovered"
    # Manifest GET discovery is sequential. Enable barrier only for known deps.
    concurrent.get_started = 3
    assert transfer(concurrent, recovered, ref, "recover") == receipt
    _, restored = reopen(recovered, ref)
    assert restored == original
    clean(concurrent)


@pytest.mark.parametrize(
    "fault,error", [("dependency", ArtifactError), ("interrupt", KeyboardInterrupt)]
)
def test_dependency_failure_or_interruption_prevents_root_and_joins(
    tmp_path, fault, error
):
    root = tmp_path / "original"
    ref = candidate(root)
    client = OverlappingS3(fault=fault)
    # No first-readback barrier on a failed upload wave.
    client.get_started = 3
    with pytest.raises(error):
        transfer(client, root, ref)
    assert not any(
        kind == "put" and key.endswith(ref.key) for kind, key in client.calls
    )
    clean(client)
    assert not list(root.rglob(".staging-*"))


def test_atomic_wire_budget_across_parallel_readbacks():
    client = ControlledS3()
    refs = [reference(bytes([index]) * 64) for index in range(3)]
    for index, ref in enumerate(refs):
        client.objects["connector/objects/" + ref.key] = bytes([index]) * 64
    worker = BoundedConnectorWorkers(3)
    store = adapter(
        client,
        transfer=replace(TransferBounds(), wire_bytes=100),
        cancelled=worker.cancelled,
    )
    with pytest.raises(ArtifactLimitError):
        worker.run([lambda ref=ref: list(store.read(ref)) for ref in refs])
    assert store.wire_bytes <= 100
    assert all(body.closed for body in client.closed_bodies)
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())


def test_atomic_object_budget_does_not_multiply_with_workers():
    client = ControlledS3()
    from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
    from tests.integration.test_connector_cli import ARTIFACT

    worker = BoundedConnectorWorkers(3)
    store = S3ArtifactStore(
        client,
        "test-bucket",
        "connector/",
        replace(ARTIFACT, objects=1),
        cancelled=worker.cancelled,
    )
    with pytest.raises(ArtifactLimitError):
        worker.run(
            [
                lambda index=index: store.put_exact(
                    reference(bytes([index])), [bytes([index])]
                )
                for index in range(3)
            ]
        )
    assert len(store.objects) <= 1
    assert all(body.closed for body in client.closed_bodies)


def test_concurrent_conflicting_existing_dependency_prevents_root(tmp_path):
    root = tmp_path / "original"
    ref = candidate(root)
    store, _ = reopen(root, ref)
    graph = LocalConnectorEvidence(store).graph(ref, MODEL)
    client = ControlledS3()
    client.objects["connector/objects/" + graph[0].key] = b"conflicting existing bytes"
    before = dict(client.objects)
    worker = BoundedConnectorWorkers(3)
    durable = adapter(client, cancelled=worker.cancelled)
    with pytest.raises(ArtifactError):
        PersistConnectorArtifacts(
            LocalConnectorEvidence(store, worker), durable, workers=worker
        ).execute(ref, MODEL)
    assert client.objects["connector/objects/" + graph[0].key] == next(
        iter(before.values())
    )
    assert not any(
        kind == "put" and key.endswith(ref.key) for kind, key in client.calls
    )
    assert all(body.closed for body in client.closed_bodies)


@pytest.mark.parametrize("stage", ["root", "readback"])
def test_parallel_final_manifest_or_full_readback_failure_has_no_receipt(
    tmp_path, stage
):
    root = tmp_path / "local"
    ref = candidate(root)
    client = ControlledS3()
    original_put, original_get = client.put_object, client.get_object
    root_seen = False

    def put(**kwargs):
        nonlocal root_seen
        if kwargs["Key"].endswith(ref.key):
            root_seen = True
            if stage == "root":
                raise failure("AccessDenied")
        return original_put(**kwargs)

    root_reads = 0

    def get(**kwargs):
        nonlocal root_reads
        if kwargs["Key"].endswith(ref.key):
            root_reads += 1
            if stage == "readback" and root_reads == 2:
                raise failure("AccessDenied")
        return original_get(**kwargs)

    client.put_object, client.get_object = put, get
    with pytest.raises(ArtifactError):
        transfer(client, root, ref)
    assert root_seen
    assert all(body.closed for body in client.closed_bodies)
    assert not any(t.name.startswith("connector_") for t in threading.enumerate())
