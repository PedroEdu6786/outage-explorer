"""Current local access precedes publication lookup, even for an empty catalog."""

from dataclasses import dataclass

from outage_explorer.application.catalog_responses import (
    CatalogDatasetResult,
    CatalogResult,
)
from outage_explorer.application.dto import CatalogAccess
from outage_explorer.application.errors import DataUnavailableError
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import DatasetSummary


@dataclass(frozen=True)
class CatalogEntry:
    dataset: Dataset
    generation_id: str | None
    coverage: DatasetSummary | None


class CatalogService:
    def __init__(self, publications: ResourcePublicationStore) -> None:
        self._publications = publications

    def list(self, catalog_access: CatalogAccess) -> tuple[CatalogEntry, ...]:
        datasets = catalog_access.datasets
        active = self._publications.active_generation()
        if active is None:
            return tuple(CatalogEntry(dataset, None, None) for dataset in datasets)

        active.validate()
        coverage_by_grain = {summary.grain: summary for summary in active.datasets}
        return tuple(
            CatalogEntry(
                dataset,
                active.id,
                coverage_by_grain[AnalyticalGrain(dataset.grain)],
            )
            for dataset in datasets
        )

    def describe(
        self, catalog_access: CatalogAccess, encoding: TabularEncoding
    ) -> CatalogResult:
        entries = self.list(catalog_access)
        generation_id = entries[0].generation_id if entries else None
        if generation_id is None:
            raise DataUnavailableError("Published data unavailable")
        return CatalogResult(
            generation_id=generation_id,
            datasets=tuple(
                CatalogDatasetResult(
                    dataset=entry.dataset,
                    columns=encoding.columns(entry.dataset.columns),
                    coverage=entry.coverage,
                )
                for entry in entries
            ),
        )
