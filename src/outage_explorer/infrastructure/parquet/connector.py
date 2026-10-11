"""Explicit local resource recovery and staged legacy graph consumers."""

from collections.abc import Iterable, Iterator

from outage_explorer.application.ports.artifacts import StoredObject
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
from outage_explorer.infrastructure.parquet.resource_restoration import ResourceRestorer
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


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
        restorer = ResourceRestorer(self.store, self.verify_baseline, self.workers)
        return restorer.restore(receipt, source, bounds)

    def read(self, reference: StoredObject) -> Iterator[bytes]:
        return self.store.read(reference)
