"""Bounded publication reads that pin each dataset's exact resource Parquet file."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.compute as pc  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class ResourceObjects(Protocol):
    """Exact-descriptor reads only: no metadata lookup, listing or manifest."""

    def read(self, reference: StoredObject) -> Iterator[bytes]: ...


@dataclass(frozen=True)
class CacheBounds:
    bytes: int
    files: int
    rows: int
    preparation_seconds: int

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Positive modeled cache bounds required")


@dataclass
class _Entry:
    generation: DatasetSummary
    dataset: Dataset
    files: tuple[ApprovedFile, ...]
    pins: int = 0


_FILES = {"national": "national", "facility": "facilities", "generator": "generators"}


class _Pin:
    def __init__(
        self,
        cache: "_PrivateCache",
        identity: tuple[str, str],
        files: tuple[ApprovedFile, ...],
    ) -> None:
        self._cache, self._identity, self._files = cache, identity, files
        self._closed = False

    @property
    def files(self) -> tuple[ApprovedFile, ...]:
        return self._files

    def close(self) -> None:
        with self._cache._lock:
            if not self._closed:
                self._cache._entries[self._identity].pins -= 1
                self._closed = True


class _PrivateCache:
    """Pinned, bounded, private disposable unified resource files."""

    def __init__(
        self,
        root: Path,
        artifacts: ArtifactBounds,
        bounds: CacheBounds,
    ) -> None:
        self._root, self._artifacts, self._bounds = root, artifacts, bounds
        self._entries: dict[tuple[str, str], _Entry] = {}
        self._lock = RLock()
        self._closed = False
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or any(root.iterdir()):
            raise ValueError("Modeled cache requires an empty private directory")

    @staticmethod
    def _verify(file: ApprovedFile) -> None:
        path = Path(file.path)
        if path.is_symlink() or path.stat().st_size != file.byte_count:
            raise ArtifactError("Cached modeled identity mismatch")
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(65536):
                digest.update(chunk)
        if digest.hexdigest() != file.sha256:
            raise ArtifactError("Cached modeled checksum mismatch")

    def _evict(self, incoming: int, files: int) -> None:
        def fits() -> bool:
            existing = [
                file for entry in self._entries.values() for file in entry.files
            ]
            return (
                incoming + sum(f.byte_count for f in existing) <= self._bounds.bytes
                and files + len(existing) <= self._bounds.files
            )

        for identity, entry in tuple(self._entries.items()):
            if fits():
                return
            if not entry.pins:
                for file in entry.files:
                    Path(file.path).unlink(missing_ok=True)
                del self._entries[identity]
        if not fits():
            raise ArtifactLimitError("Pinned modeled cache capacity exhausted")

    def close(self) -> None:
        """Remove only owned disposable files, after all input leases finish."""
        with self._lock:
            if any(entry.pins for entry in self._entries.values()):
                raise ValueError("Active modeled input leases")
            for entry in self._entries.values():
                for file in entry.files:
                    Path(file.path).unlink(missing_ok=True)
            self._entries.clear()
            self._closed = True


class VerifiedResourceCache(_PrivateCache):
    """Pins one exact resource file per dataset from its publication descriptor.

    A cold read fetches only the described object: no manifest, metadata lookup
    or listing. The unified file is verified for bytes, SHA-256, schema, rows and
    coverage, then scanned in place; analytical views project public columns.
    """

    def __init__(
        self,
        root: Path,
        objects: ResourceObjects,
        artifacts: ArtifactBounds,
        bounds: CacheBounds,
    ) -> None:
        super().__init__(root, artifacts, bounds)
        self._objects = objects

    def prepare(
        self, generation: ResourcePublishedGeneration, dataset: Dataset
    ) -> _Pin:
        with self._lock:
            if self._closed:
                raise DataUnavailableError("Modeled cache closed")
            started = monotonic()

            def check() -> None:
                if monotonic() - started >= self._bounds.preparation_seconds:
                    raise ArtifactLimitError("Modeled preparation deadline exceeded")

            try:
                generation.validate()
                summary = next(
                    item
                    for item in generation.datasets
                    if item.grain.value == dataset.grain
                )
                if dataset.id != _FILES[dataset.grain] or dataset.schema_version != "1":
                    raise ArtifactError("Dataset does not match its resource grain")
                if (
                    summary.rows > self._bounds.rows
                    or (summary.byte_count or 0) > self._bounds.bytes
                ):
                    raise ArtifactLimitError("Resource descriptor exceeds cache budget")
                # Identical verified bytes are one cache object across generations.
                identity = (str(summary.sha256), dataset.id)
                retained = replace(summary, object_key=None)
                if identity not in self._entries:
                    self._load(summary, dataset, identity, check)
                entry = self._entries[identity]
                if entry.generation != retained or entry.dataset != dataset:
                    raise ArtifactError("Cached publication identity mismatch")
                for file in entry.files:
                    check()
                    self._verify(file)
                entry.pins += 1
                return _Pin(self, identity, entry.files)
            except ArtifactLimitError:
                raise AnalyticalResourceError("Modeled input resource limit") from None
            except (
                ArtifactError,
                OSError,
                ValueError,
                StopIteration,
                pa.ArrowException,
            ):
                raise DataUnavailableError(
                    "Published modeled input unavailable"
                ) from None

    def _load(
        self,
        summary: DatasetSummary,
        dataset: Dataset,
        identity: tuple[str, str],
        check: Callable[[], None],
    ) -> None:
        if (
            summary.object_key is None
            or summary.sha256 is None
            or summary.byte_count is None
        ):
            raise ArtifactError("Resource descriptor incomplete")
        exact = StoredObject(summary.object_key, summary.sha256, summary.byte_count)
        # Local content identity is the SHA-256; the physical key is only used to
        # read. The staged copy must reproduce the exact descriptor bytes.
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
            self._verify_coverage(staging.root / local.key, summary, check)
            check()
            self._evict(summary.byte_count, 1)
            target = self._root / f"{summary.sha256}-{dataset.id}.parquet"
            os.replace(staging.root / local.key, target)
            try:
                target.chmod(0o400)
                self._entries[identity] = _Entry(
                    replace(summary, object_key=None),
                    dataset,
                    (
                        ApprovedFile(
                            str(target),
                            summary.sha256,
                            summary.byte_count,
                            summary.rows,
                        ),
                    ),
                )
            except BaseException:
                target.unlink(missing_ok=True)
                raise

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


class ResourceReadSessions:
    """Each exact descriptor read opens a fresh bounded transfer session."""

    def __init__(self, factory: Callable[[], ResourceObjects]) -> None:
        self._factory = factory

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        return self._factory().read(reference)


def reclaim_private_cache(root: Path, *, file_limit: int) -> None:
    """Only after exclusive analytical ownership and dead-worker reconciliation.

    This namespace contains disposable modeled files and preparation copies only.
    Unknown paths fail closed rather than expanding the teardown authority.
    """
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
    ):
        raise ValueError("Private modeled cache unavailable")
    paths: list[Path] = []
    for path in root.iterdir():
        if len(paths) >= file_limit:
            raise ValueError("Private cache recovery limit exceeded")
        info = path.lstat()
        if info.st_uid != os.getuid() or path.is_symlink():
            raise ValueError("Invalid disposable cache file")
        if stat.S_ISREG(info.st_mode) and re.fullmatch(
            r"[0-9a-f]{64}-(national|facilities|generators)\.parquet", path.name
        ):
            paths.append(path)
        elif stat.S_ISDIR(info.st_mode) and path.name.startswith(".preparing-"):
            # Interrupted download directory contents are not durable artifacts.
            paths.append(path)
        else:
            raise ValueError("Unknown private cache path")
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
