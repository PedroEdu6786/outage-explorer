"""One SQL submission and retained reads share the same transport path."""

from flask import Blueprint

from outage_explorer.application.services.access.service import AccessService
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.requests.data import (
    query_page_request,
    query_submission_request,
)
from outage_explorer.entrypoints.http.requests.query import (
    QueryPageRequest,
    QuerySubmissionRequest,
)
from outage_explorer.entrypoints.http.responses.base import (
    JsonPayloadResponse,
    respond_with,
)
from outage_explorer.entrypoints.http.transport.auth import AuthTransport
from outage_explorer.entrypoints.http.transport.guards import (
    authenticated,
    csrf_protected,
    validated_request,
)


def create_queries_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("queries", __name__)

    @blueprint.post("/api/query")
    @csrf_protected(access, transport)
    @validated_request(query_submission_request)
    @respond_with(JsonPayloadResponse)
    def execute(
        *, credential: str, validated: QuerySubmissionRequest, **_: object
    ) -> object:
        return services.queries.execute(
            credential,
            validated.sql,
            page=validated.page,
            page_size=validated.page_size,
        )

    @blueprint.get("/api/query")
    @authenticated(access, transport)
    @validated_request(query_page_request)
    @respond_with(JsonPayloadResponse)
    def page(*, credential: str, validated: QueryPageRequest, **_: object) -> object:
        return services.query_pages.read(
            credential,
            validated.query_id,
            page=validated.page,
            page_size=validated.page_size,
        )

    return blueprint
