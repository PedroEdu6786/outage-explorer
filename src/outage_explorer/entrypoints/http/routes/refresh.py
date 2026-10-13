"""Durable refresh receipts without source work or worker lifetime ownership."""

from flask import Blueprint

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
    empty_request,
    refresh_admission_request,
    refresh_status_request,
)
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.refresh_responses import (
    RefreshAdmissionResponse,
    RefreshLatestResponse,
    RefreshStatusResponse,
)
from outage_explorer.entrypoints.http.responses import respond_with


def create_refresh_blueprint(
    services: DataServices, access: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("refresh", __name__)

    @blueprint.post("/api/refresh")
    @csrf_protected(access, transport)
    @roles_required(access, transport, "admin")
    @validated_request(refresh_admission_request)
    @respond_with(RefreshAdmissionResponse)
    def admit(
        *,
        request_access: RequestAccess,
        validated: RefreshAdmissionRequest,
        **_: object,
    ) -> object:
        return services.refresh.admit(request_access, validated)

    @blueprint.get("/api/refresh/latest")
    @roles_required(access, transport, "admin")
    @validated_request(empty_request)
    @respond_with(RefreshLatestResponse)
    def latest(*, request_access: RequestAccess, **_: object) -> object:
        return services.refresh.latest(request_access)

    @blueprint.get("/api/refresh/<run_id>")
    @roles_required(access, transport, "admin")
    @validated_request(refresh_status_request, route_parameters=("run_id",))
    @respond_with(RefreshStatusResponse)
    def status(*, request_access: RequestAccess, validated: str, **_: object) -> object:
        return services.refresh.status(request_access, validated)

    return blueprint
