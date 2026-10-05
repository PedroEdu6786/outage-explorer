"""Sanitized auth failures; never serialize exception text."""

from flask import Flask, Response, jsonify, make_response, request
from werkzeug.exceptions import HTTPException

from outage_explorer.application.errors import (
    ForbiddenError,
    InvalidRequestError,
    UnauthenticatedError,
)


def error_response(error: Exception, *, login: bool = False) -> Response:
    if isinstance(error, UnauthenticatedError):
        status, code, message = (
            (400, "login_failed", "Login failed")
            if login
            else (401, "unauthenticated", "Authentication required")
        )
    elif isinstance(error, ForbiddenError):
        status, code, message = 403, "forbidden", "Access denied"
    elif isinstance(error, InvalidRequestError):
        status, code, message = 400, "invalid_request", "Invalid request"
    else:
        status, code, message = 503, "service_unavailable", "Service unavailable"
    response = jsonify(error={"code": code, "message": message})
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


def register_auth_errors(app: Flask) -> None:
    @app.errorhandler(HTTPException)
    def framework_error(error: HTTPException) -> Response:
        if request.path.startswith("/api/auth/"):
            return error_response(InvalidRequestError("Invalid request"))
        return make_response(error.get_response())
