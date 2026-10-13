"""Public catalog response projection."""

from dataclasses import dataclass
from typing import Self

from outage_explorer.application.catalog_responses import (
    CatalogDatasetResult,
    CatalogResult,
)
from outage_explorer.entrypoints.http.responses.base import ResponseData


@dataclass(frozen=True)
class CatalogDatasetResponse:
    result: CatalogDatasetResult

    def build(self) -> dict[str, object]:
        dataset = self.result.dataset
        filters = ["start_date", "end_date"]
        if dataset.id != "national":
            filters.append("facility")

        coverage = self.result.coverage
        return {
            "id": dataset.id,
            "sql_name": dataset.id,
            "label": dataset.label,
            "schema_version": dataset.schema_version,
            "columns": self.result.columns,
            "supported_filters": filters,
            "coverage": None
            if coverage is None
            else {
                "start_date": coverage.start.isoformat(),
                "end_date": coverage.end.isoformat(),
            },
        }


@dataclass(frozen=True)
class CatalogResponse:
    result: CatalogResult

    @classmethod
    def from_result(cls, result: CatalogResult) -> Self:
        return cls(result)

    def build(self) -> ResponseData:
        return ResponseData(
            body={
                "generation_id": self.result.generation_id,
                "datasets": [
                    CatalogDatasetResponse(dataset).build()
                    for dataset in self.result.datasets
                ],
            }
        )
