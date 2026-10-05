"""Host-only persistent cookies and exact browser origin transport."""

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from flask import Response, request

from outage_explorer.application.errors import ForbiddenError


@dataclass(frozen=True)
class AuthTransport:
    ui_origin: str
    allowed_origins: frozenset[str]
    development_http: bool = False

    @property
    def session_cookie(self) -> str:
        return "outage_session" if self.development_http else "__Host-outage_session"

    @property
    def attempt_cookie(self) -> str:
        return "outage_login" if self.development_http else "__Host-outage_login"

    def credential(self) -> str:
        return request.cookies.get(self.session_cookie, "")

    def binding(self) -> str:
        return request.cookies.get(self.attempt_cookie, "")

    def mutation_csrf(self) -> str:
        if request.headers.get("Origin") not in self.allowed_origins:
            raise ForbiddenError("Access denied")
        return request.headers.get("X-CSRF-Token", "")

    def set_cookie(
        self, response: Response, name: str, value: str, expires: datetime
    ) -> None:
        response.set_cookie(
            name,
            value,
            expires=expires,
            path="/",
            secure=not self.development_http,
            httponly=True,
            samesite="Lax",
        )

    def clear_cookie(self, response: Response, name: str) -> None:
        response.delete_cookie(
            name,
            path="/",
            secure=not self.development_http,
            httponly=True,
            samesite="Lax",
        )

    def finalize(self, response: Response) -> Response:
        response.headers["Cache-Control"] = "no-store"
        response.headers.add("Vary", "Origin")
        origin = request.headers.get("Origin")
        if origin in self.allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
        return response

    def preflight(self) -> Response:
        if request.headers.get(
            "Origin"
        ) not in self.allowed_origins or request.headers.get(
            "Access-Control-Request-Method"
        ) not in {"GET", "POST"}:
            raise ForbiddenError("Access denied")
        requested = {
            item.strip().lower()
            for item in request.headers.get("Access-Control-Request-Headers", "").split(
                ","
            )
            if item.strip()
        }
        if requested - {"x-csrf-token", "content-type"}:
            raise ForbiddenError("Access denied")
        response = Response(status=204)
        response.headers["Access-Control-Allow-Methods"] = "GET, POST"
        response.headers["Access-Control-Allow-Headers"] = "X-CSRF-Token, Content-Type"
        return response


class CallbackLogFilter(logging.Filter):
    """Remove URL queries from Werkzeug access logs, including callback codes."""

    def filter(self, record: logging.LogRecord) -> bool:
        def scrub(value: object) -> object:
            return (
                re.sub(r"\?[^\s]*", "?[redacted]", value)
                if isinstance(value, str)
                else value
            )

        record.msg = scrub(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: scrub(value) for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(scrub(value) for value in record.args)
        return True
