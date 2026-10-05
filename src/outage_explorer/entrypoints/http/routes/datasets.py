"""Catalog and preview transport; use cases enforce current analytical access."""

from flask import Blueprint, Response, jsonify

from outage_explorer.application.errors import DatasetUnavailableError, ForbiddenError
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import parameters, preview_parameters
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.errors import data_error_response


def create_datasets_blueprint(
    services: DataServices, transport: AuthTransport
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
    def preview(dataset: str) -> Response:
        values = preview_parameters()
        try:
            return jsonify(
                services.preview.page(
                    transport.credential(),
                    dataset,
                    start=values.start,
                    end=values.end,
                    size=values.size,
                    cursor=values.cursor,
                )
            )
        except (DatasetUnavailableError, ForbiddenError) as error:
            # Unknown/forbidden ID must not disclose the available projection.
            return data_error_response(error, dataset=True)

    return blueprint
