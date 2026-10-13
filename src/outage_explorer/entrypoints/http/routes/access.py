"""Thin auth routes; application services own identity/session decisions."""

from functools import partial

from flask import Blueprint

from outage_explorer.application.dto import CurrentIdentity
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.requests.auth import (
    CallbackQuery,
    LoginQuery,
    callback_query,
    login_query,
)
from outage_explorer.entrypoints.http.requests.data import empty_request
from outage_explorer.entrypoints.http.responses.access import (
    CallbackResponse,
    LoginResponse,
    LogoutResponse,
    SessionResponse,
    respond_with_auth,
)
from outage_explorer.entrypoints.http.responses.base import respond_with
from outage_explorer.entrypoints.http.transport.auth import AuthTransport
from outage_explorer.entrypoints.http.transport.guards import (
    authenticated,
    csrf_protected,
    logout_if_authenticated,
    validated_request,
)


def create_access_blueprint(
    login_service: LoginService, access_service: AccessService, transport: AuthTransport
) -> Blueprint:
    blueprint = Blueprint("access", __name__, url_prefix="/api/auth")

    @blueprint.get("/login")
    @validated_request(login_query)
    @respond_with_auth(LoginResponse, transport)
    def login(*, validated: LoginQuery) -> object:
        return login_service.begin(validated.return_to)

    @blueprint.get("/callback")
    @validated_request(partial(callback_query, binding=transport.binding))
    @respond_with_auth(CallbackResponse, transport)
    def callback(*, validated: CallbackQuery) -> object:
        return login_service.complete(
            validated.code, validated.state, validated.browser_binding
        )

    @blueprint.get("/session")
    @authenticated(access_service, transport)
    @validated_request(empty_request)
    @respond_with(SessionResponse)
    def session(*, identity: CurrentIdentity, **_: object) -> object:
        return identity

    @blueprint.post("/logout")
    @csrf_protected(access_service, transport, allow_invalid_session=True)
    @validated_request(empty_request)
    @respond_with_auth(LogoutResponse, transport)
    @logout_if_authenticated
    def logout(*, credential: str, **_: object) -> None:
        return access_service.logout(credential)

    return blueprint
