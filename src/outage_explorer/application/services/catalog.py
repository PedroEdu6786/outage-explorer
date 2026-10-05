"""Current local access precedes publication lookup, even for an empty catalog."""

from dataclasses import dataclass

from outage_explorer.application.ports.publication import PublicationStore
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
    def __init__(self, access: AccessService, publications: PublicationStore) -> None:
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
