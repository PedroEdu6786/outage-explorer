"""Typed catalog results without HTTP response construction."""

from dataclasses import dataclass

from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import DatasetSummary


@dataclass(frozen=True)
class CatalogDatasetResult:
    dataset: Dataset
    columns: list[dict[str, object]]
    coverage: DatasetSummary | None


@dataclass(frozen=True)
class CatalogResult:
    generation_id: str
    datasets: tuple[CatalogDatasetResult, ...]
