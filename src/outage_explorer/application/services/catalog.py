"""Current local access precedes publication lookup, even for an empty catalog."""

from dataclasses import dataclass

from outage_explorer.application.errors import DataUnavailableError
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation, AnalyticalGrain, Role
from outage_explorer.domain.datasets import PUBLIC_DATASETS, Dataset
from outage_explorer.domain.publication import DatasetSummary


@dataclass(frozen=True)
class CatalogEntry:
    dataset: Dataset
    generation_id: str | None
    coverage: DatasetSummary | None


class CatalogService:
    def __init__(
        self, access: AccessService, publications: ResourcePublicationStore
    ) -> None:
        self._access = access
        self._publications = publications

    def list(self, token: str) -> tuple[CatalogEntry, ...]:
        identity = self._access.resolve(token)
        datasets = tuple(
            item
            for item in PUBLIC_DATASETS
            if identity.user.role is not Role.VIEWER or item.id == "national"
        )
        self._access.authorize(
            token,
            AccessOperation.ANALYTICAL,
            grains=frozenset(AnalyticalGrain(item.grain) for item in datasets),
        )
        active = self._publications.active_generation()
        if active is not None:
            active.validate()
        return tuple(
            CatalogEntry(
                dataset,
                None if active is None else active.id,
                None
                if active is None
                else next(
                    item
                    for item in active.datasets
                    if item.grain.value == dataset.grain
                ),
            )
            for dataset in datasets
        )

    def payload(self, token: str, encoding: TabularEncoding) -> dict[str, object]:
        entries = self.list(token)
        if not entries or entries[0].generation_id is None:
            raise DataUnavailableError("Published data unavailable")
        return {
            "generation_id": entries[0].generation_id,
            "datasets": [
                {
                    "id": entry.dataset.id,
                    "sql_name": entry.dataset.id,
                    "label": entry.dataset.label,
                    "schema_version": entry.dataset.schema_version,
                    "columns": encoding.columns(entry.dataset.columns),
                    "supported_filters": ["start_date", "end_date"],
                    "coverage": None
                    if entry.coverage is None
                    else {
                        "start_date": entry.coverage.start.isoformat(),
                        "end_date": entry.coverage.end.isoformat(),
                    },
                }
                for entry in entries
            ],
        }
