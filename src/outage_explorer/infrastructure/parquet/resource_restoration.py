"""Restore exact resource files, preserving existing files on failure."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import partial

from outage_explorer.application.ports.artifacts import ArtifactError, ArtifactRef
from outage_explorer.application.ports.candidates import ResourceBaseline
from outage_explorer.application.ports.connector import (
    DurableResourceReceipt,
    ResourceTransfers,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


@dataclass(frozen=True)
class ResourceDownload:
    """Keep the S3 address and its corresponding local identity together."""

    remote: ArtifactRef
    local: ArtifactRef

    def transfer(self, source: ResourceTransfers, store: LocalParquetStore) -> None:
        chunks = source.read(self.remote.object)
        try:
            restored = store.put_immutable(chunks, expected=self.local.object)
            if restored != self.local.object:
                raise ArtifactError("Recovered resource identity mismatch")
        finally:
            close = getattr(chunks, "close", None)
            if close is not None:
                close()


class ResourceRestorer:
    def __init__(
        self,
        store: LocalParquetStore,
        verify_baseline: Callable[[ResourceBaseline, RefreshBounds], None],
        workers: ConnectorWorkers | None = None,
    ) -> None:
        self.store = store
        self.verify_baseline = verify_baseline
        self.workers = workers

    def restore(
        self,
        receipt: DurableResourceReceipt,
        source: ResourceTransfers,
        bounds: RefreshBounds,
    ) -> ResourceBaseline:
        source.validate_receipt(receipt)
        resources = self._local_references(receipt)
        baseline = ResourceBaseline(
            receipt.generation_id,
            resources,
            receipt.contract_id,
            receipt.transformation_id,
            receipt.schema_version,
        )
        downloads = self._missing_files(receipt.resources, resources)
        missing_references = tuple(download.local for download in downloads)
        self.store.check_recovery_capacity(missing_references)
        download_bytes = sum(ref.object.byte_count for ref in missing_references)

        with source.recovery_staging(download_bytes):
            try:
                self._download_files(downloads, source)
                self.verify_baseline(baseline, bounds)
                return baseline
            except BaseException:
                # Worker.run joins all tasks before raising. Existing files are
                # never included in downloads and must survive failed recovery.
                for reference in missing_references:
                    self.store.discard_owned(reference.object)
                raise

    @staticmethod
    def _local_references(receipt: DurableResourceReceipt) -> tuple[ArtifactRef, ...]:
        local_references = []
        for remote in receipt.resources:
            local_object = replace(remote.object, key=remote.object.sha256)
            local_references.append(replace(remote, object=local_object))
        return tuple(local_references)

    def _missing_files(
        self, remote: tuple[ArtifactRef, ...], local: tuple[ArtifactRef, ...]
    ) -> tuple[ResourceDownload, ...]:
        downloads = []
        for remote_reference, local_reference in zip(remote, local, strict=True):
            if self.store.contains(local_reference.object):
                self.store.adopt_exact(local_reference)
            else:
                downloads.append(ResourceDownload(remote_reference, local_reference))
        return tuple(downloads)

    def _download_files(
        self, downloads: tuple[ResourceDownload, ...], source: ResourceTransfers
    ) -> None:
        if self.workers is None:
            for download in downloads:
                download.transfer(source, self.store)
            return

        tasks = tuple(
            partial(download.transfer, source, self.store) for download in downloads
        )
        self.workers.run(tasks)
