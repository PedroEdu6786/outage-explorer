"""Immutable transfers reach disk incrementally and admit only verified files."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier

import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_parquet import ARTIFACT_BOUNDS


def identity(payload):
    digest = hashlib.sha256(payload).hexdigest()
    return StoredObject(digest, digest, len(payload))


def test_chunks_reach_disk_before_source_is_exhausted(tmp_path):
    chunk = b"a" * (2**20)
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)

    def source():
        yield chunk
        staging = tuple(tmp_path.glob(".staging-*"))
        assert len(staging) == 1
        assert staging[0].read_bytes() == chunk
        assert store._objects == set()
        yield b"tail"

    reference = store.put_immutable(source(), expected=identity(chunk + b"tail"))
    assert (tmp_path / reference.key).read_bytes() == chunk + b"tail"
    assert list(tmp_path.iterdir()) == [tmp_path / reference.key]
    assert store._bytes == reference.byte_count


@pytest.mark.parametrize(
    "failure",
    ["file", "expected", "hash", "short", "empty", "type", "source", "deadline"],
)
def test_failed_transfer_removes_partial_file_and_preserves_existing(tmp_path, failure):
    store = LocalParquetStore(tmp_path, replace(ARTIFACT_BOUNDS, file_bytes=8))
    existing = store.put_immutable([b"valid"])
    expected = identity(b"abcdefgh")

    def source():
        if failure == "empty":
            return
        yield b"abcd"
        if failure == "file":
            yield b"efghi"
        elif failure == "expected":
            yield b"e"
        elif failure == "hash":
            yield b"xxxx"
        elif failure == "type":
            yield "efgh"
        elif failure == "source":
            raise RuntimeError("interrupted source")
        elif failure == "deadline":

            def expired():
                raise ArtifactLimitError("deadline")

            store.check = expired
        # short and deadline deliberately exhaust after the initial chunk.

    if failure == "expected":
        expected = identity(b"abcd")
    with pytest.raises((ArtifactError, RuntimeError)):
        store.put_immutable(source(), expected=expected)
    store.check = lambda: None
    store.verify_object(existing)
    assert list(tmp_path.iterdir()) == [tmp_path / existing.key]
    assert store._objects == {existing.key}
    assert store._bytes == existing.byte_count
    assert store.put_immutable([b"new"]) == identity(b"new")


@pytest.mark.parametrize("same", [False, True])
def test_parallel_sources_are_not_locked_and_charge_unique_objects_once(tmp_path, same):
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    barrier = Barrier(2, timeout=5)
    payloads = [b"first", b"first" if same else b"second"]

    def transfer(payload):
        def source():
            yield payload
            barrier.wait()

        return store.put_immutable(source())

    with ThreadPoolExecutor(max_workers=2) as workers:
        references = list(workers.map(transfer, payloads))
    assert references == [identity(payload) for payload in payloads]
    assert store._bytes == sum(len(payload) for payload in set(payloads))
    assert len(list(tmp_path.iterdir())) == len(set(payloads))


@pytest.mark.parametrize("bound", ["total", "objects"])
def test_final_admission_failure_cleans_staging_and_duplicate_is_idempotent(
    tmp_path, bound
):
    bounds = (
        replace(ARTIFACT_BOUNDS, total_bytes=5)
        if bound == "total"
        else replace(ARTIFACT_BOUNDS, objects=1)
    )
    store = LocalParquetStore(tmp_path, bounds)
    existing = store.put_immutable([b"valid"])
    assert store.put_immutable([b"valid"]) == existing
    with pytest.raises(ArtifactLimitError):
        store.put_immutable([b"other"])
    assert list(tmp_path.iterdir()) == [tmp_path / existing.key]
    assert store._bytes == 5


def test_existing_corrupt_file_is_not_overwritten(tmp_path):
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    expected = identity(b"valid")
    path = tmp_path / expected.key
    path.write_bytes(b"wrong")
    with pytest.raises(ArtifactError):
        store.put_immutable([b"valid"], expected=expected)
    assert path.read_bytes() == b"wrong"
    assert list(tmp_path.iterdir()) == [path]
    assert store._bytes == 0


@pytest.mark.parametrize("operation", ["fsync", "link"])
def test_disk_failure_removes_staging_without_admitting_object(
    tmp_path, monkeypatch, operation
):
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)

    def fail(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(
        f"outage_explorer.infrastructure.parquet.storage.os.{operation}", fail
    )
    with pytest.raises(ArtifactError, match="Cannot persist immutable object"):
        store.put_immutable([b"valid"])
    assert list(tmp_path.iterdir()) == []
    assert store._objects == set()
    assert store._bytes == 0
