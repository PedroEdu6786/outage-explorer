"""One SQL submission and retained reads share the same transport path."""

from flask import Blueprint, Response, jsonify, request

from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import query_parameters
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.errors import data_error_response


def create_queries_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("queries", __name__)

    @blueprint.errorhandler(Exception)
    def failure(error: Exception) -> Response:
        return data_error_response(error)

    @blueprint.before_request
    def preflight() -> Response | None:
        return transport.preflight() if request.method == "OPTIONS" else None

    @blueprint.post("/api/query")
    def execute() -> Response:
        credential = transport.credential()
        access.validate_csrf(credential, transport.mutation_csrf())
        sql, page, size = query_parameters(submission=True)
        assert size is not None
        return jsonify(
            services.queries.execute(credential, sql, page=page, page_size=size)
        )

    @blueprint.get("/api/query")
    def page() -> Response:
        identity, page, size = query_parameters(submission=False)
        return jsonify(
            services.queries.page(
                transport.credential(), identity, page=page, page_size=size
            )
        )

    return blueprint
