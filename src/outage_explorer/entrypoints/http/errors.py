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
        if request.path.startswith(("/api/datasets", "/api/query", "/api/refresh")):
            return data_error_response(InvalidRequestError("Invalid request"))
        if request.path.startswith("/api/auth/"):
            return error_response(InvalidRequestError("Invalid request"))
        return make_response(error.get_response())


def data_error_response(error: Exception, *, dataset: bool = False) -> Response:
    """Map known failures with fixed public text, never exception diagnostics."""
    from outage_explorer.application import errors
    from outage_explorer.application.ports.sql_inspection import SqlRejected

    if isinstance(error, HTTPException):
        error = InvalidRequestError("Invalid request")
    retry = None
    details = None
    status, code, message = 503, "service_unavailable", "Service unavailable"
    if dataset and isinstance(
        error, (errors.ForbiddenError, errors.DataUnavailableError)
    ):
        status, code, message = 404, "dataset_unavailable", "Dataset unavailable"
    elif isinstance(error, errors.QueryPageError):
        status, code, message = 400, error.code, "Invalid retained result page"
        from outage_explorer.application.data_payloads import query_error_details

        details = query_error_details(error.identity)
    elif isinstance(error, SqlRejected):
        status, code, message = 400, error.code, "SQL rejected"
    elif isinstance(error, errors.InvalidRequestError):
        status, code, message = 400, "invalid_request", "Invalid request"
    elif isinstance(error, errors.UnauthenticatedError):
        status, code, message = 401, "unauthenticated", "Authentication required"
    elif isinstance(error, errors.ForbiddenError):
        status, code, message = 403, "forbidden", "Access denied"
    elif isinstance(error, errors.QueryExpiredError):
        status, code, message = 410, "query_unavailable", "Query unavailable"
    elif isinstance(error, errors.QueryUnavailableError):
        status, code, message = 404, "query_unavailable", "Query unavailable"
    elif isinstance(error, errors.PreviewUnavailableError):
        status, code, message = 410, "preview_unavailable", "Preview unavailable"
    elif isinstance(error, errors.DataUnavailableError):
        status, code, message = 503, "data_unavailable", "Data unavailable"
    elif isinstance(error, errors.RefreshBusyError):
        status, code, message, retry = 409, "refresh_busy", "Refresh busy", 3
    elif isinstance(error, errors.IdempotencyConflictError):
        status, code, message = 409, "idempotency_conflict", "Idempotency conflict"
    elif isinstance(error, errors.AnalyticalBusyError):
        status, code, message, retry = 503, "query_busy", "Query busy", 3
    elif isinstance(error, errors.AnalyticalTimeoutError):
        status, code, message = 504, "query_timeout", "Query timed out"
    elif isinstance(error, errors.AnalyticalResourceError):
        status, code, message = 422, "query_resource_limit", "Query resource limit"
    elif isinstance(error, errors.ResultCapacityError):
        status, code, message, retry = (
            429 if error.per_user else 503,
            "result_capacity_exhausted",
            "Result capacity exhausted",
            3,
        )
    elif isinstance(error, errors.PreviewCapacityError):
        status, code, message, retry = (
            503,
            "service_unavailable",
            "Service unavailable",
            3,
        )
    payload: dict[str, object] = {"code": code, "message": message}
    if details is not None:
        payload["details"] = details
    if retry is not None:
        payload["retry_after_seconds"] = retry
    response = jsonify(error=payload)
    response.status_code = status
    if retry is not None:
        response.headers["Retry-After"] = str(retry)
    response.headers["Cache-Control"] = "no-store"
    return response
