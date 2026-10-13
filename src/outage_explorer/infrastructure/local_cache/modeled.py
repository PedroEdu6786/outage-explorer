"""Prepare published resource files for isolated analytical reads."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

import pyarrow as pa  # type: ignore[import-untyped]

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.local_cache.inventory import (
    CacheEntry,
    CacheIdentity,
    CacheInventory,
    CachePin,
)
from outage_explorer.infrastructure.local_cache.recovery import (
    reclaim_private_cache as _reclaim_private_cache,
)
from outage_explorer.infrastructure.local_cache.resource_loader import (
    ResourceFileLoader,
    ResourceObjects,
)

_FILES = {"national": "national", "facility": "facilities", "generator": "generators"}


@dataclass(frozen=True)
class CacheBounds:
    bytes: int
    files: int
    rows: int
    preparation_seconds: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Positive modeled cache bounds required")


class VerifiedResourceCache:
    """Resolve a descriptor, verify its file, and pin it until release."""

    def __init__(
        self,
        root: Path,
        objects: ResourceObjects,
        artifacts: ArtifactBounds,
        bounds: CacheBounds,
    ) -> None:
        self._inventory = CacheInventory(root, bounds.bytes, bounds.files)
        self._loader = ResourceFileLoader(root, objects, artifacts)
        self._bounds = bounds
        # Retain these inspection points for existing integration diagnostics.
        self._root = root
        self._entries = self._inventory.entries

    def prepare(
        self, generation: ResourcePublishedGeneration, dataset: Dataset
    ) -> CachePin:
        with self._inventory.lock:
            if self._inventory.closed:
                raise DataUnavailableError("Modeled cache closed")
            started = monotonic()

            def check() -> None:
                if monotonic() - started >= self._bounds.preparation_seconds:
                    raise ArtifactLimitError("Modeled preparation deadline exceeded")

            try:
                summary = self._summary_for(generation, dataset)
                identity, entry = self._entry_for(summary, dataset, check)
                for file in entry.files:
                    check()
                    self._loader.verify_cached(file)
                return self._inventory.pin(identity, entry)
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

    def _summary_for(
        self, generation: ResourcePublishedGeneration, dataset: Dataset
    ) -> DatasetSummary:
        generation.validate()
        if dataset.id != _FILES[dataset.grain] or dataset.schema_version != "1":
            raise ArtifactError("Dataset does not match its resource grain")
        summary = next(
            item for item in generation.datasets if item.grain.value == dataset.grain
        )
        if (
            summary.rows > self._bounds.rows
            or (summary.byte_count or 0) > self._bounds.bytes
        ):
            raise ArtifactLimitError("Resource descriptor exceeds cache budget")
        return summary

    def _entry_for(
        self,
        summary: DatasetSummary,
        dataset: Dataset,
        check: Callable[[], None],
    ) -> tuple[CacheIdentity, CacheEntry]:
        # Identical verified bytes are shared across generations.
        identity = (str(summary.sha256), dataset.id)
        entry = self._inventory.find(identity, summary, dataset)
        if entry is None:
            with self._loader.staged(summary, dataset, check) as staged:
                entry = self._inventory.install(staged, summary, dataset, identity)
        return identity, entry

    def close(self) -> None:
        self._inventory.close()


class ResourceReadSessions:
    """Each exact descriptor read opens a fresh bounded transfer session."""

    def __init__(self, factory: Callable[[], ResourceObjects]) -> None:
        self._factory = factory

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        return self._factory().read(reference)


def reclaim_private_cache(root: Path, *, file_limit: int) -> None:
    """Reclaim after exclusive ownership and dead-worker reconciliation."""
    _reclaim_private_cache(root, file_limit=file_limit)
