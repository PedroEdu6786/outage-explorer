"""Catalog transport and guarded, validated preview reads."""

from flask import Blueprint

from outage_explorer.application.dto import PreviewAccess, RequestAccess
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.auth_helpers import (
    authenticated,
    dataset_required,
    roles_required,
    validated_request,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import (
    empty_request,
    preview_parameters,
)
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.responses import JsonPayloadResponse, respond_with


def create_datasets_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("datasets", __name__)

    @blueprint.get("/api/datasets")
    @authenticated(access, transport)
    @validated_request(empty_request)
    @respond_with(JsonPayloadResponse)
    def catalog(*, credential: str, **_: object) -> object:
        return services.catalog.payload(credential, services.encoding)

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
