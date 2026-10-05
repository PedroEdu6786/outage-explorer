"""Thin auth routes; application services own identity/session decisions."""

from flask import Blueprint, Response, jsonify, make_response, redirect, request

from outage_explorer.application.dto import CurrentIdentity
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.auth_helpers import (
    authenticated,
    csrf_protected,
    validated_request,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.errors import error_response
from outage_explorer.entrypoints.http.schemas import (
    CallbackQuery,
    LoginQuery,
    callback_query,
    identity_payload,
    login_query,
)


def create_access_blueprint(
    login_service: LoginService, access_service: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("access", __name__, url_prefix="/api/auth")

    @blueprint.errorhandler(Exception)
    def failure(error: Exception) -> Response:
        response = error_response(
            error, login=request.endpoint in {"access.login", "access.callback"}
        )
        if request.endpoint == "access.callback":
            transport.clear_cookie(response, transport.attempt_cookie)
        return response

    @blueprint.before_request
    def preflight() -> Response | None:
        if request.method == "OPTIONS":
            return transport.preflight()
        return None

    @blueprint.get("/login")
    @validated_request(login_query)
    def login(*, validated: LoginQuery) -> Response:
        result = login_service.begin(validated.return_to)
        response = make_response(redirect(result.authorization_url))
        transport.set_cookie(
            response,
            transport.attempt_cookie,
            result.browser_binding,
            result.expires_at,
        )
        return response

    @blueprint.get("/callback")
    @validated_request(callback_query)
    def callback(*, validated: CallbackQuery) -> Response:
        result = login_service.complete(
            validated.code, validated.state, transport.binding()
        )
        response = make_response(redirect(transport.ui_origin + result.return_to))
        transport.set_cookie(
            response, transport.session_cookie, result.token, result.expires_at
        )
        transport.clear_cookie(response, transport.attempt_cookie)
        return response

    @blueprint.get("/session")
    @authenticated(access_service, transport)
    def session(*, credential: str, identity: CurrentIdentity) -> Response:
        return jsonify(identity_payload(identity))

    @blueprint.post("/logout")
    @csrf_protected(access_service, transport, allow_invalid_session=True)
    def logout(*, credential: str, csrf_validated: bool) -> Response:
        if csrf_validated:
            access_service.logout(credential)
        response = Response(status=204)
        transport.clear_cookie(response, transport.session_cookie)
        return response

    return blueprint
