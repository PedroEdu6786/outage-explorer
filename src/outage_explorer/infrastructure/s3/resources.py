"""Application-facing adapter for exact generation-scoped S3 resources."""

import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager
from threading import Event
from typing import Any

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactRef,
    StoredObject,
    TransferBounds,
)
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.infrastructure.s3.resource_addresses import ResourceAddresses
from outage_explorer.infrastructure.s3.resource_object_transfer import (
    ResourceObjectTransfer,
)
from outage_explorer.infrastructure.s3.transfer_budget import TransferBudget


class S3ResourceStore:
    """Coordinate address validation, shared limits and verified S3 transfer."""

    def __init__(
        self,
        client: Any,
        bucket: str,
        prefix: str,
        bounds: ArtifactBounds,
        transfer: TransferBounds | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        cancelled: Event | None = None,
    ) -> None:
        self._addresses = ResourceAddresses(bucket, prefix)
        limits = TransferBounds() if transfer is None else transfer
        self._budget = TransferBudget(bounds, limits, monotonic, cancelled)
        self._transfer = ResourceObjectTransfer(client, bucket, limits, self._budget)

    def _admit(self, reference: StoredObject) -> None:
        self._budget.deadline()
        self._addresses.key(reference)
        self._budget.register(reference)

    def addresses(
        self, generation_id: str, resources: tuple[ArtifactRef, ...]
    ) -> tuple[ArtifactRef, ...]:
        addressed = self._addresses.addresses(generation_id, resources)
        for reference in addressed:
            self._admit(reference.object)
        return addressed

    def validate_receipt(self, receipt: DurableResourceReceipt) -> None:
        self._addresses.validate_receipt(receipt)
        for reference in receipt.resources:
            self._admit(reference.object)

    def put_verified(
        self, reference: ArtifactRef, chunks: Iterable[bytes]
    ) -> ArtifactRef:
        self._addresses.validate_upload(reference)
        self._admit(reference.object)
        self._transfer.upload_and_verify(reference.object, chunks)
        return reference

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        self._admit(reference)
        yield from self._transfer.read(reference)

    def verify(self, reference: StoredObject) -> None:
        for _ in self.read(reference):
            pass

    def recovery_staging(self, size: int) -> AbstractContextManager[None]:
        """Hold the shared reservation through restoration and worker cleanup."""
        return self._budget.staging(size)
