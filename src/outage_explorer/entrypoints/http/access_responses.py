"""Auth response DTOs, including dedicated redirect/cookie transport handling."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, Protocol, Self

from flask import Response, make_response, redirect

from outage_explorer.application.dto import (
    CurrentIdentity,
    EstablishedSession,
    LoginRedirect,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.responses import ResponseData
from outage_explorer.entrypoints.http.schemas import identity_payload


@dataclass(frozen=True)
class SessionResponse:
    identity: CurrentIdentity

    @classmethod
    def from_result(cls, result: CurrentIdentity) -> Self:
        return cls(result)

    def build(self) -> ResponseData:
        return ResponseData(body=identity_payload(self.identity))


class AuthResponseDTO(Protocol):
    @classmethod
    def from_result(cls, result: Any) -> Self: ...

    def build(self, transport: AuthTransport) -> Response: ...


def respond_with_auth(
    response_dto: type[AuthResponseDTO], transport: AuthTransport
) -> Callable[[Callable[..., object]], Callable[..., Response]]:
    """Preserve non-JSON auth contracts without Flask work in controllers."""

    def decorate(handler: Callable[..., object]) -> Callable[..., Response]:
        @wraps(handler)
        def responded(*args: object, **kwargs: object) -> Response:
            return response_dto.from_result(handler(*args, **kwargs)).build(transport)

        return responded

    return decorate


@dataclass(frozen=True)
class LoginResponse:
    result: LoginRedirect

    @classmethod
    def from_result(cls, result: LoginRedirect) -> Self:
        return cls(result)

    def build(self, transport: AuthTransport) -> Response:
        response = make_response(redirect(self.result.authorization_url))
        transport.set_cookie(
            response,
            transport.attempt_cookie,
            self.result.browser_binding,
            self.result.expires_at,
        )
        return response


@dataclass(frozen=True)
class CallbackResponse:
    result: EstablishedSession

    @classmethod
    def from_result(cls, result: EstablishedSession) -> Self:
        return cls(result)

    def build(self, transport: AuthTransport) -> Response:
        response = make_response(redirect(transport.ui_origin + self.result.return_to))
        transport.set_cookie(
            response,
            transport.session_cookie,
            self.result.token,
            self.result.expires_at,
        )
        transport.clear_cookie(response, transport.attempt_cookie)
        return response


@dataclass(frozen=True)
class LogoutResponse:
    @classmethod
    def from_result(cls, result: None) -> Self:
        return cls()

    def build(self, transport: AuthTransport) -> Response:
        response = Response(status=204)
        transport.clear_cookie(response, transport.session_cookie)
        return response
