"""Already constructed application services accepted by the inert factory."""

from dataclasses import dataclass

from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.services.catalog import CatalogService
from outage_explorer.application.services.preview import PreviewService
from outage_explorer.application.services.queries import QueryService
from outage_explorer.application.services.refresh import RefreshService


@dataclass(frozen=True)
class DataServices:
    catalog: CatalogService
    preview: PreviewService
    queries: QueryService
    refresh: RefreshService
    encoding: TabularEncoding
