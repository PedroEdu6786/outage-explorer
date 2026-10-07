"""Explicit local resource recovery and staged legacy graph consumers."""

import logging
from collections.abc import Iterable, Iterator
from dataclasses import replace
from functools import partial

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
    SanitizedPage,
    TransientInput,
)
from outage_explorer.application.ports.connector import (
    DurableResourceReceipt,
    ResourceTransfers,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.candidates import ParquetResourceBuilder
from outage_explorer.infrastructure.parquet.evidence import collect_resources
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

_LOG = logging.getLogger("outage_explorer.connector.parquet")


class LocalConnectorEvidence:
    def __init__(
        self, store: LocalParquetStore, workers: ConnectorWorkers | None = None
    ) -> None:
        self.store, self.workers = store, workers

    def collect_resources(self, pages: Iterable[SanitizedPage]) -> TransientInput:
        return collect_resources(self.store, pages)

    def verify_baseline(
        self, baseline: ResourceBaseline, bounds: RefreshBounds
    ) -> None:
        ParquetResourceBuilder(self.store).verify_baseline(baseline, bounds)

    def verify_candidate(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> None:
        ParquetResourceBuilder(self.store).verify_resources(candidate, bounds)

    def restore_resources(
        self,
        receipt: DurableResourceReceipt,
        source: ResourceTransfers,
        bounds: RefreshBounds,
    ) -> ResourceBaseline:
        """Recover exact supplied files; remove only recovery-owned files on failure.

        GET streams belong to transfer tasks. The worker's run joins all tasks
        before cleanup, including cancellation/failure; pre-existing caller files
        are never recovery-owned. No descriptor discovery or source replay occurs.
        """
        source.validate_receipt(receipt)
        refs = tuple(
            replace(ref, object=replace(ref.object, key=ref.object.sha256))
            for ref in receipt.resources
        )
        baseline = ResourceBaseline(
            receipt.generation_id,
            refs,
            receipt.contract_id,
            receipt.transformation_id,
            receipt.schema_version,
        )
        # Admission accounts every known size before SDK access. Existing files
        # are validated, then charged exactly once; new files share write caps.
        new = tuple(ref for ref in refs if not self.store._path(ref.object).exists())
        for ref in refs:
            if ref not in new:
                self.store.adopt_exact(ref)
        with self.store._lock:
            if (
                len(self.store._objects) + len(new) > self.store.bounds.objects
                or self.store._bytes
                + self.store._transient_bytes
                + sum(ref.object.byte_count for ref in new)
                > self.store.bounds.total_bytes
            ):
                raise ArtifactLimitError(
                    "Resource recovery exceeds aggregate staging bounds"
                )

        def transfer(remote: ArtifactRef, local: ArtifactRef) -> None:
            chunks = source.read(remote.object)
            try:
                restored = self.store.put_immutable(chunks, expected=local.object)
                if restored != local.object:
                    raise ArtifactError("Recovered resource identity mismatch")
            finally:
                close = getattr(chunks, "close", None)
                if close is not None:
                    close()

        tasks = tuple(
            partial(transfer, remote, local)
            for remote, local in zip(receipt.resources, refs, strict=True)
            if local in new
        )
        with source.recovery_staging(sum(ref.object.byte_count for ref in new)):
            try:
                if self.workers is None:
                    for task in tasks:
                        task()
                else:
                    self.workers.run(tasks)
                self.verify_baseline(baseline, bounds)
                return baseline
            except BaseException:
                # run() has joined; no task still owns one of these files/streams.
                for ref in new:
                    self.store.discard_owned(ref.object)
                raise

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        return self.store.read(reference)
