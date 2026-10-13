"""One aggregate resource budget shared by concurrent S3 transfers."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, RLock

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    StoredObject,
    TransferBounds,
)
from outage_explorer.infrastructure.synchronization import with_instance_lock


class TransferBudget:
    def __init__(
        self,
        bounds: ArtifactBounds,
        transfer: TransferBounds,
        monotonic: Callable[[], float] = time.monotonic,
        cancelled: Event | None = None,
    ) -> None:
        self.bounds = bounds
        self.transfer = transfer
        self.monotonic = monotonic
        self.cancelled = Event() if cancelled is None else cancelled
        self.started = monotonic()
        self.lock = RLock()
        self.requests = 0
        self.wire_bytes = 0
        self.temporary_bytes = 0
        self.objects: dict[str, StoredObject] = {}
        self.object_bytes = 0

    def deadline(self) -> None:
        if (
            self.cancelled.is_set()
            or self.monotonic() - self.started >= self.transfer.elapsed_seconds
        ):
            raise ArtifactLimitError("Artifact transfer deadline exhausted")

    @with_instance_lock("lock")
    def register(self, reference: StoredObject) -> None:
        self.deadline()
        if type(reference.byte_count) is not int or not (
            0 < reference.byte_count <= min(self.bounds.file_bytes, 5_000_000_000)
        ):
            raise ArtifactLimitError("Artifact file bound exceeded")
        existing = self.objects.get(reference.key)
        if existing is not None:
            if existing != reference:
                raise ArtifactError("Conflicting resource descriptor")
            return
        if (
            len(self.objects) >= self.bounds.objects
            or self.object_bytes + reference.byte_count > self.bounds.total_bytes
        ):
            raise ArtifactLimitError("Artifact graph bound exceeded")
        self.objects[reference.key] = reference
        self.object_bytes += reference.byte_count

    @with_instance_lock("lock")
    def charge(self, size: int) -> None:
        self.deadline()
        if self.wire_bytes + size > self.transfer.wire_bytes:
            self.cancelled.set()
            raise ArtifactLimitError("Artifact transfer byte bound exceeded")
        self.wire_bytes += size

    @with_instance_lock("lock")
    def request(self) -> None:
        self.deadline()
        if self.requests >= self.transfer.requests:
            self.cancelled.set()
            raise ArtifactLimitError("Artifact transfer request bound exceeded")
        self.requests += 1

    @contextmanager
    def staging(self, size: int) -> Iterator[None]:
        self._reserve_staging(size)
        try:
            yield
        finally:
            self._release_staging(size)

    @with_instance_lock("lock")
    def _reserve_staging(self, size: int) -> None:
        self.deadline()
        if self.temporary_bytes + size > self.transfer.temporary_bytes:
            self.cancelled.set()
            raise ArtifactLimitError("Aggregate temporary disk bound exceeded")
        self.temporary_bytes += size

    @with_instance_lock("lock")
    def _release_staging(self, size: int) -> None:
        self.temporary_bytes -= size
