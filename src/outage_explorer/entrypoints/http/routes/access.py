"""Thin auth routes; application services own identity/session decisions."""

from flask import Blueprint, Response, jsonify, make_response, redirect, request

from outage_explorer.application.errors import UnauthenticatedError
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.errors import error_response
from outage_explorer.entrypoints.http.schemas import identity_payload, query_value


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
    def login() -> Response:
        result = login_service.begin(query_value("return_to", default="/"))
        response = make_response(redirect(result.authorization_url))
        transport.set_cookie(
            response,
            transport.attempt_cookie,
            result.browser_binding,
            result.expires_at,
        )
        return response

    @blueprint.get("/callback")
    def callback() -> Response:
        if "error" in request.args:
            raise UnauthenticatedError("Login failed")
        result = login_service.complete(
            query_value("code"), query_value("state"), transport.binding()
        )
        response = make_response(redirect(transport.ui_origin + result.return_to))
        transport.set_cookie(
            response, transport.session_cookie, result.token, result.expires_at
        )
        transport.clear_cookie(response, transport.attempt_cookie)
        return response

    @blueprint.get("/session")
    def session() -> Response:
        return jsonify(
            identity_payload(access_service.current_identity(transport.credential()))
        )

    @blueprint.post("/logout")
    def logout() -> Response:
        csrf = transport.mutation_csrf()
        credential = transport.credential()
        try:
            access_service.validate_csrf(credential, csrf)
        except UnauthenticatedError:
            pass
        else:
            access_service.logout(credential)
        response = Response(status=204)
        transport.clear_cookie(response, transport.session_cookie)
        return response

    return blueprint
