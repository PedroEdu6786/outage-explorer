"""Durable refresh receipts without source work or worker lifetime ownership."""

from flask import Blueprint, Response, jsonify, request

from outage_explorer.application.data_payloads import refresh_payload
from outage_explorer.application.dto import RequestAccess
from outage_explorer.application.refresh_request import RefreshAdmissionRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.entrypoints.http.auth_helpers import (
    csrf_protected,
    roles_required,
    validated_request,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import (
    identifier,
    parameters,
    refresh_admission_request,
)
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.errors import data_error_response


def create_refresh_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("refresh", __name__)

    @blueprint.errorhandler(Exception)
    def failure(error: Exception) -> Response:
        return data_error_response(error)

    @blueprint.before_request
    def preflight() -> Response | None:
        methods = {"POST"} if request.path == "/api/refresh" else {"GET"}
        return (
            transport.preflight(methods=methods, idempotency=True)
            if request.method == "OPTIONS"
            else None
        )

    @blueprint.post("/api/refresh")
    @csrf_protected(access, transport)
    @roles_required(access, transport, "admin")
    @validated_request(refresh_admission_request)
    def admit(
        *,
        request_access: RequestAccess,
        validated: RefreshAdmissionRequest,
        **_: object,
    ) -> Response:
        run = services.refresh.admit(request_access, validated)
        url = "/api/refresh/" + run.id
        response = jsonify(
            run_id=run.id,
            status=run.status.value,
            effective_interval=refresh_payload(run)["effective_interval"],
            status_url=url,
        )
        response.status_code = 200 if run.status.terminal else 202
        response.headers["Location"] = url
        response.headers["Retry-After"] = "3"
        return response

    @blueprint.get("/api/refresh/latest")
    @roles_required(access, transport, "admin")
    def latest(*, request_access: RequestAccess) -> Response:
        parameters(set())
        run = services.refresh.latest(request_access)
        return jsonify(run=None if run is None else refresh_payload(run))

    @blueprint.get("/api/refresh/<run_id>")
    @roles_required(access, transport, "admin")
    def status(run_id: str, *, request_access: RequestAccess) -> Response:
        parameters(set())
        run = services.refresh.status(request_access, identifier(run_id))
        if run is None:
            response = jsonify(
                error={"code": "refresh_unavailable", "message": "Refresh unavailable"}
            )
            response.status_code = 404
            return response
        return jsonify(refresh_payload(run))

    return blueprint
