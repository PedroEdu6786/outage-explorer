"""Catalog result and HTTP projection retain the established public contract."""

from datetime import date
from unittest.mock import Mock

import pytest

from outage_explorer.application.catalog_responses import CatalogResult
from outage_explorer.application.errors import DataUnavailableError
from outage_explorer.application.services.catalog import CatalogEntry, CatalogService
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import DatasetSummary
from outage_explorer.entrypoints.http.responses.catalog import CatalogResponse


def test_catalog_service_returns_typed_result_and_response_projects_coverage():
    national, facilities = PUBLIC_DATASETS[:2]
    coverage = DatasetSummary(
        grain=AnalyticalGrain.FACILITY,
        schema_version="1",
        rows=5,
        start=date(2026, 9, 1),
        end=date(2026, 9, 2),
        object_key="private-object-key",
    )
    service = CatalogService(Mock())
    service.list = Mock(
        return_value=(
            CatalogEntry(national, "generation", None),
            CatalogEntry(facilities, "generation", coverage),
        )
    )
    encoding = Mock()
    encoding.columns.side_effect = lambda columns: [
        {"name": column.name} for column in columns
    ]

    result = service.describe("session-token", encoding)
    assert isinstance(result, CatalogResult)
    assert result.generation_id == "generation"
    assert encoding.columns.call_count == 2

    body = CatalogResponse.from_result(result).build().body
    assert isinstance(body, dict)
    assert body["generation_id"] == "generation"
    assert body["datasets"][0]["supported_filters"] == ["start_date", "end_date"]
    assert body["datasets"][1]["supported_filters"] == [
        "start_date",
        "end_date",
        "facility",
    ]
    assert body["datasets"][1]["coverage"] == {
        "start_date": "2026-09-01",
        "end_date": "2026-09-02",
    }
    assert "private-object-key" not in str(body)


def test_catalog_without_publication_fails_before_column_encoding():
    service = CatalogService(Mock())
    service.list = Mock(return_value=(CatalogEntry(PUBLIC_DATASETS[0], None, None),))
    encoding = Mock()

    with pytest.raises(DataUnavailableError):
        service.describe("session-token", encoding)

    encoding.columns.assert_not_called()
