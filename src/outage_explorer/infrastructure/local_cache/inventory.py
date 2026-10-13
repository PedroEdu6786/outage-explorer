"""Local cache ownership, capacity, and active file leases."""

import os
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock

from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import DatasetSummary

CacheIdentity = tuple[str, str]


@dataclass
class CacheEntry:
    summary: DatasetSummary
    dataset: Dataset
    files: tuple[ApprovedFile, ...]
    pins: int = 0


class CachePin:
    def __init__(
        self,
        inventory: "CacheInventory",
        identity: CacheIdentity,
        files: tuple[ApprovedFile, ...],
    ) -> None:
        self._inventory = inventory
        self._identity = identity
        self._files = files
        self._closed = False

    @property
    def files(self) -> tuple[ApprovedFile, ...]:
        return self._files

    def close(self) -> None:
        self._inventory.release(self)


class CacheInventory:
    """Own admitted files and prevent eviction while they are leased."""

    def __init__(self, root: Path, byte_limit: int, file_limit: int) -> None:
        self.root = root
        self.byte_limit = byte_limit
        self.file_limit = file_limit
        self.entries: dict[CacheIdentity, CacheEntry] = {}
        self.lock = RLock()
        self.closed = False
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if root.is_symlink() or any(root.iterdir()):
            raise ValueError("Modeled cache requires an empty private directory")

    def find(
        self, identity: CacheIdentity, summary: DatasetSummary, dataset: Dataset
    ) -> CacheEntry | None:
        entry = self.entries.get(identity)
        if entry is not None and (
            entry.summary != replace(summary, object_key=None)
            or entry.dataset != dataset
        ):
            raise ArtifactError("Cached publication identity mismatch")
        return entry

    def install(
        self,
        staged: Path,
        summary: DatasetSummary,
        dataset: Dataset,
        identity: CacheIdentity,
    ) -> CacheEntry:
        if summary.byte_count is None or summary.sha256 is None:
            raise ArtifactError("Resource descriptor incomplete")
        self._evict_for(summary.byte_count)
        target = self.root / f"{summary.sha256}-{dataset.id}.parquet"
        os.replace(staged, target)
        try:
            target.chmod(0o400)
            file = ApprovedFile(
                str(target), summary.sha256, summary.byte_count, summary.rows
            )
            entry = CacheEntry(replace(summary, object_key=None), dataset, (file,))
            self.entries[identity] = entry
            return entry
        except BaseException:
            target.unlink(missing_ok=True)
            raise

    def pin(self, identity: CacheIdentity, entry: CacheEntry) -> CachePin:
        entry.pins += 1
        return CachePin(self, identity, entry.files)

    def release(self, pin: CachePin) -> None:
        with self.lock:
            if not pin._closed:
                self.entries[pin._identity].pins -= 1
                pin._closed = True

    def close(self) -> None:
        with self.lock:
            if any(entry.pins for entry in self.entries.values()):
                raise ValueError("Active modeled input leases")
            for entry in self.entries.values():
                for file in entry.files:
                    Path(file.path).unlink(missing_ok=True)
            self.entries.clear()
            self.closed = True

    def _evict_for(self, incoming_bytes: int) -> None:
        used_bytes = sum(
            file.byte_count for entry in self.entries.values() for file in entry.files
        )
        used_files = sum(len(entry.files) for entry in self.entries.values())
        for identity, entry in tuple(self.entries.items()):
            if (
                used_bytes + incoming_bytes <= self.byte_limit
                and used_files + 1 <= self.file_limit
            ):
                return
            if not entry.pins:
                for file in entry.files:
                    Path(file.path).unlink(missing_ok=True)
                    used_bytes -= file.byte_count
                    used_files -= 1
                del self.entries[identity]
        if (
            used_bytes + incoming_bytes > self.byte_limit
            or used_files + 1 > self.file_limit
        ):
            raise ArtifactLimitError("Pinned modeled cache capacity exhausted")
