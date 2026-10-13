"""Strict bounded transport input; no authorization or analytical work."""

import json
import re
from datetime import date
from urllib.parse import unquote_to_bytes

from flask import request

from outage_explorer.application.errors import InvalidRequestError
from outage_explorer.application.preview_request import PreviewRequest
from outage_explorer.application.refresh_request import RefreshAdmissionRequest
from outage_explorer.entrypoints.http.query_requests import (
    QueryPageRequest,
    QuerySubmissionRequest,
)

MAX_BODY_BYTES = 131072
MAX_QUERY_BYTES = 8192
MAX_ID_BYTES = 4096


def parameters(allowed: set[str], *, body: bool = False) -> dict[str, str]:
    if len(request.query_string) > MAX_QUERY_BYTES:
        raise InvalidRequestError("Invalid request")
    if not body and request.get_data(cache=True):
        raise InvalidRequestError("Invalid request")
    if any(
        key not in allowed or len(values) != 1 for key, values in request.args.lists()
    ):
        raise InvalidRequestError("Invalid request")
    return dict(request.args)


def positive(
    value: str | None, default: int | None = None, *, maximum: int = 2147483647
) -> int:
    if value is None and default is not None:
        return default
    if value is None or re.fullmatch(r"[1-9][0-9]{0,9}", value, flags=re.ASCII) is None:
        raise InvalidRequestError("Invalid request")
    result = int(value)
    if result > maximum:
        raise InvalidRequestError("Invalid request")
    return result


def identifier(value: str | None) -> str:
    if not value or len(value.encode()) > MAX_ID_BYTES:
        raise InvalidRequestError("Invalid request")
    return value


def day(value: str | None) -> date | None:
    if value is None:
        return None
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value, flags=re.ASCII) is None:
        raise InvalidRequestError("Invalid request")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidRequestError("Invalid request") from None


def json_object(fields: set[str]) -> dict[str, object]:
    if request.mimetype != "application/json" or request.content_encoding:
        raise InvalidRequestError("Invalid request")
    raw = request.get_data(cache=True)
    if len(raw) > MAX_BODY_BYTES:
        raise InvalidRequestError("Invalid request")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise InvalidRequestError("Invalid request")
            result[key] = value
        return result

    try:
        value = json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidRequestError("Invalid request") from None
    if not isinstance(value, dict) or set(value) != fields:
        raise InvalidRequestError("Invalid request")
    return value


def empty_request() -> None:
    """Reject query parameters and bodies for endpoints with no request inputs."""
    parameters(set())


def refresh_status_request(*, run_id: str) -> str:
    empty_request()
    return identifier(run_id)


def refresh_admission_request() -> RefreshAdmissionRequest:
    parameters(set(), body=True)
    json_object(set())
    return RefreshAdmissionRequest.parse(
        idempotency_key=request.headers.get("Idempotency-Key", "")
    )


def preview_parameters(*, dataset: str) -> PreviewRequest:
    query = parameters({"start_date", "end_date", "page_size", "cursor", "facility"})
    validate_query_encoding()

    start_date = day(query.get("start_date"))
    end_date = day(query.get("end_date"))
    facility = query.get("facility")

    page_size = None
    if "page_size" in query:
        page_size = positive(query["page_size"])

    cursor = None
    if "cursor" in query:
        cursor = identifier(query["cursor"])

    return PreviewRequest.parse(
        dataset=dataset,
        start=start_date,
        end=end_date,
        size=page_size,
        facility=facility,
        cursor=cursor,
    )


def validate_query_encoding() -> None:
    """Reject invalid UTF-8 before percent escapes can become identifiers."""
    # Werkzeug preserves malformed UTF-8 as percent escapes. Validate the
    # bounded transport bytes so an invalid encoding cannot become an ID.
    try:
        unquote_to_bytes(request.query_string).decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise InvalidRequestError("Invalid request") from None


def query_submission_request() -> QuerySubmissionRequest:
    values = parameters({"page", "page_size"}, body=True)
    return QuerySubmissionRequest.parse(
        sql=json_object({"sql"})["sql"],
        page=positive(values.get("page"), 1),
        page_size=positive(values.get("page_size"), 100),
    )


def query_page_request() -> QueryPageRequest:
    values = parameters({"query_id", "page", "page_size"})
    return QueryPageRequest.parse(
        query_id=values.get("query_id"),
        page=positive(values.get("page")),
        page_size=positive(values["page_size"]) if "page_size" in values else None,
    )
