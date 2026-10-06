"""Bounded modeled-only publication reads and pinned public Parquet projections."""

import hashlib
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Protocol

import pyarrow as pa  # type: ignore[import-untyped]
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
    StoredObject,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import PublishedGeneration
from outage_explorer.infrastructure.parquet.manifests import load_manifest
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    schema_for,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


class PublishedObjects(Protocol):
    def reference(self, key: str, digest: str) -> StoredObject: ...
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
    generation: PublishedGeneration
    dataset: Dataset
    files: tuple[ApprovedFile, ...]
    pins: int = 0


class _Pin:
    def __init__(
        self,
        cache: "VerifiedModeledCache",
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


class VerifiedModeledCache:
    def __init__(
        self,
        root: Path,
        objects: PublishedObjects,
        artifacts: ArtifactBounds,
        bounds: CacheBounds,
    ) -> None:
        self._root, self._objects, self._artifacts, self._bounds = (
            root,
            objects,
            artifacts,
            bounds,
        )
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

    def prepare(self, generation: PublishedGeneration, dataset: Dataset) -> _Pin:
        with self._lock:
            if self._closed:
                raise DataUnavailableError("Modeled cache closed")
            identity = (generation.manifest_digest, dataset.id)
            started = monotonic()

            def check() -> None:
                if monotonic() - started >= self._bounds.preparation_seconds:
                    raise ArtifactLimitError("Modeled preparation deadline exceeded")

            try:
                generation.validate()
                if identity not in self._entries:
                    self._load(generation, dataset, identity, check)
                entry = self._entries[identity]
                if entry.generation != generation or entry.dataset != dataset:
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
        generation: PublishedGeneration,
        dataset: Dataset,
        identity: tuple[str, str],
        check: Callable[[], None],
    ) -> None:
        # A staging session downloads only the manifest and selected modeled files.
        # Raw/provenance dependencies are neither fetched nor granted to a worker.
        guard = check
        with tempfile.TemporaryDirectory(
            dir=self._root, prefix=".preparing-"
        ) as directory:
            staging = LocalParquetStore(
                Path(directory) / "objects", self._artifacts, guard
            )

            def download(reference: StoredObject) -> None:
                if staging.put_immutable(self._objects.read(reference)) != reference:
                    raise ArtifactError("Published object identity mismatch")

            manifest_ref = self._objects.reference(
                generation.manifest_key, generation.manifest_digest
            )
            if (
                manifest_ref.key != generation.manifest_key
                or manifest_ref.sha256 != generation.manifest_digest
            ):
                raise ArtifactError("Published manifest reference mismatch")
            download(manifest_ref)
            manifest = load_manifest(staging, manifest_ref)
            if (
                manifest.generation_id != generation.id
                or manifest.base_generation_id != generation.base_generation_id
                or manifest.outcome != "candidate"
            ):
                raise ArtifactError("Publication manifest identity mismatch")
            summary = next(
                item
                for item in generation.datasets
                if item.grain.value == dataset.grain
            )
            refs = tuple(ref for ref in manifest.modeled if ref.grain == dataset.grain)
            if (
                not refs
                or sum(ref.row_count for ref in refs) != summary.rows
                or summary.rows > self._bounds.rows
            ):
                raise ArtifactLimitError(
                    "Published modeled row count unavailable or over budget"
                )
            if any(
                ref.kind != "modeled" or ref.schema_version != dataset.schema_version
                for ref in refs
            ):
                raise ArtifactError("Invalid modeled references")
            keys: set[tuple[str, ...]] = set()
            dates = []
            prepared: list[ApprovedFile] = []
            for index, ref in enumerate(refs):
                download(ref.object)
                records = []
                for record in staging.records(ref):
                    guard()
                    row = modeled_from_record(record, dataset.grain)
                    key = (row.observation.day.isoformat(), *row.observation.identity)
                    if key in keys or row.observation.day != ref.partition:
                        raise ArtifactError("Duplicate or misplaced modeled key")
                    keys.add(key)
                    dates.append(row.observation.day)
                    records.append(
                        {col.name: record[col.name] for col in dataset.columns}
                    )
                schema = schema_for("modeled", dataset.grain)
                public_schema = pa.schema(
                    [schema.field(col.name) for col in dataset.columns]
                )
                projected = Path(directory) / f"projection-{index}.parquet"
                pq.write_table(
                    pa.Table.from_pylist(records, schema=public_schema), projected
                )
                size = projected.stat().st_size
                if (
                    size > self._artifacts.file_bytes
                    or sum(file.byte_count for file in prepared) + size
                    > self._bounds.bytes
                ):
                    raise ArtifactLimitError("Projected file budget exceeded")
                digest = hashlib.sha256(projected.read_bytes()).hexdigest()
                prepared.append(
                    ApprovedFile(str(projected), digest, size, len(records))
                )
            if (
                len(keys) != summary.rows
                or min(dates) != summary.start
                or max(dates) != summary.end
            ):
                raise ArtifactError("Published coverage mismatch")
            self._evict(sum(file.byte_count for file in prepared), len(prepared))
            installed: list[ApprovedFile] = []
            try:
                for index, file in enumerate(prepared):
                    target = (
                        self._root
                        / f"{generation.manifest_digest}-{dataset.id}-{index}.parquet"
                    )
                    os.replace(file.path, target)
                    target.chmod(0o400)
                    installed.append(
                        ApprovedFile(
                            str(target), file.sha256, file.byte_count, file.rows
                        )
                    )
                self._entries[identity] = _Entry(generation, dataset, tuple(installed))
            except BaseException:
                for file in installed:
                    Path(file.path).unlink(missing_ok=True)
                raise

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


class PublishedReadSessions:
    """The serialized cache opens a fresh transfer budget per manifest load."""

    def __init__(self, factory: Callable[[], PublishedObjects]) -> None:
        self._factory = factory
        self._current: PublishedObjects | None = None

    def reference(self, key: str, digest: str) -> StoredObject:
        self._current = self._factory()
        return self._current.reference(key, digest)

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        if self._current is None:
            raise ArtifactError("Published read session unavailable")
        return self._current.read(reference)


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
            r"[0-9a-f]{64}-(national|facilities|generators)-[0-9]+\.parquet", path.name
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
