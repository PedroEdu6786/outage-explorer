"""Download and verify one exact published resource before cache admission."""

import hashlib
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import DatasetSummary
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class ResourceObjects(Protocol):
    """Exact-descriptor reads only: no metadata lookup, listing or manifest."""

    def read(self, reference: StoredObject) -> Iterator[bytes]: ...


class ResourceFileLoader:
    def __init__(
        self, root: Path, objects: ResourceObjects, artifacts: ArtifactBounds
    ) -> None:
        self._root = root
        self._objects = objects
        self._artifacts = artifacts

    @contextmanager
    def staged(
        self, summary: DatasetSummary, dataset: Dataset, check: Callable[[], None]
    ) -> Iterator[Path]:
        if (
            summary.object_key is None
            or summary.sha256 is None
            or summary.byte_count is None
        ):
            raise ArtifactError("Resource descriptor incomplete")
        exact = StoredObject(summary.object_key, summary.sha256, summary.byte_count)
        # Local content identity is the SHA-256; the S3 key selects the read.
        local = StoredObject(summary.sha256, summary.sha256, summary.byte_count)
        with tempfile.TemporaryDirectory(
            dir=self._root, prefix=".preparing-"
        ) as directory:
            staging = LocalParquetStore(
                Path(directory) / "objects", self._artifacts, check
            )
            stored = staging.put_immutable(self._objects.read(exact), expected=local)
            if stored != local:
                raise ArtifactError("Published object identity mismatch")
            staging.verify(
                ArtifactRef(local, "resource", dataset.grain, None, summary.rows, "1")
            )
            path = staging.root / local.key
            self._verify_coverage(path, summary, check)
            check()
            yield path

    @staticmethod
    def verify_cached(file: ApprovedFile) -> None:
        path = Path(file.path)
        if path.is_symlink() or path.stat().st_size != file.byte_count:
            raise ArtifactError("Cached modeled identity mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        if digest.hexdigest() != file.sha256:
            raise ArtifactError("Cached modeled checksum mismatch")

    def _verify_coverage(
        self, path: Path, summary: DatasetSummary, check: Callable[[], None]
    ) -> None:
        low = high = None
        with pq.ParquetFile(path) as source:
            for batch in source.iter_batches(
                batch_size=self._artifacts.batch_rows,
                columns=["period"],
                use_threads=False,
            ):
                check()
                found = pc.min_max(batch.column("period")).as_py()
                if found["min"] is None:
                    continue
                low = found["min"] if low is None else min(low, found["min"])
                high = found["max"] if high is None else max(high, found["max"])
        if (low, high) != (summary.start, summary.end):
            raise ArtifactError("Published coverage mismatch")
