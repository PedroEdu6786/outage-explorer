"""Catalog transport and guarded, validated preview reads."""

from flask import Blueprint

from outage_explorer.application.dto import CatalogAccess, PreviewAccess, RequestAccess
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.requests.data import (
    empty_request,
    preview_parameters,
)
from outage_explorer.entrypoints.http.responses.base import (
    JsonPayloadResponse,
    respond_with,
)
from outage_explorer.entrypoints.http.responses.catalog import CatalogResponse
from outage_explorer.entrypoints.http.transport.auth import AuthTransport
from outage_explorer.entrypoints.http.transport.guards import (
    catalog_required,
    dataset_required,
    roles_required,
    validated_request,
)


def create_datasets_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("datasets", __name__)

    @blueprint.get("/api/datasets")
    @roles_required(access, transport, "viewer", "analyst", "admin")
    @catalog_required(access)
    @validated_request(empty_request)
    @respond_with(CatalogResponse)
    def catalog(*, catalog_access: CatalogAccess, **_: object) -> object:
        return services.catalog.describe(catalog_access, services.encoding)

    @blueprint.get("/api/datasets/<dataset>/preview")
    @roles_required(access, transport, "viewer", "analyst", "admin")
    @dataset_required(access)
    @validated_request(preview_parameters, route_parameters=("dataset",))
    @respond_with(JsonPayloadResponse)
    def preview(
        dataset: str,
        *,
        request_access: RequestAccess,
        preview_access: PreviewAccess,
        validated: PreviewRequest,
    ) -> object:
        return services.preview.read(preview_access, validated)

    return blueprint
