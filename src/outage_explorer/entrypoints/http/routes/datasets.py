"""Catalog transport and guarded, validated preview reads."""

from flask import Blueprint, Response, jsonify

from outage_explorer.application.dto import PreviewAccess, RequestAccess
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.auth_helpers import (
    dataset_required,
    roles_required,
    validated_request,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import parameters, preview_parameters
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.errors import data_error_response


def create_datasets_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("datasets", __name__)

    @blueprint.errorhandler(Exception)
    def failure(error: Exception) -> Response:
        return data_error_response(error)

    @blueprint.before_request
    def preflight() -> Response | None:
        from flask import request

        return (
            transport.preflight(methods={"GET"})
            if request.method == "OPTIONS"
            else None
        )

    @blueprint.get("/api/datasets")
    def catalog() -> Response:
        parameters(set())
        return jsonify(
            services.catalog.payload(transport.credential(), services.encoding)
        )

    @blueprint.get("/api/datasets/<dataset>/preview")
    @roles_required(access, transport, "viewer", "analyst", "admin")
    @dataset_required(access)
    @validated_request(preview_parameters)
    def preview(
        dataset: str,
        *,
        request_access: RequestAccess,
        preview_access: PreviewAccess,
        validated: PreviewRequest,
    ) -> Response:
        return jsonify(services.preview.read(preview_access, validated))

    return blueprint
