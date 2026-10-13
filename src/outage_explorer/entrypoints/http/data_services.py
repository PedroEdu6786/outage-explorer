"""Already constructed application services accepted by the inert factory."""

from dataclasses import dataclass

from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.services.analytical.catalog import CatalogService
from outage_explorer.application.services.analytical.preview import PreviewService
from outage_explorer.application.services.analytical.queries import QueryService
from outage_explorer.application.services.analytical.query_result_pager import (
    QueryResultPager,
)
from outage_explorer.application.services.refresh.admission import RefreshService


@dataclass(frozen=True)
class DataServices:
    catalog: CatalogService
    preview: PreviewService
    queries: QueryService
    query_pages: QueryResultPager
    refresh: RefreshService
    encoding: TabularEncoding
