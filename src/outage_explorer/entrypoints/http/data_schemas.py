"""Strict bounded transport input; no authorization or analytical work."""

import json
import re
from dataclasses import dataclass
from datetime import date

from flask import request

from outage_explorer.application.errors import InvalidRequestError

MAX_BODY_BYTES = 131072
MAX_QUERY_BYTES = 8192
MAX_SQL_BYTES = 65536
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


@dataclass(frozen=True)
class PreviewParameters:
    start: date | None = None
    end: date | None = None
    size: int | None = None
    cursor: str | None = None


def preview_parameters() -> PreviewParameters:
    values = parameters({"start_date", "end_date", "page_size", "cursor"})
    if "cursor" in values:
        if len(values) != 1:
            raise InvalidRequestError("Invalid request")
        return PreviewParameters(cursor=identifier(values["cursor"]))
    start, end = day(values.get("start_date")), day(values.get("end_date"))
    if start is not None and end is not None and start > end:
        raise InvalidRequestError("Invalid request")
    return PreviewParameters(
        start, end, positive(values.get("page_size"), 100, maximum=500)
    )


def query_parameters(*, submission: bool) -> tuple[str, int, int | None]:
    values = parameters(
        {"page", "page_size"} if submission else {"query_id", "page", "page_size"},
        body=submission,
    )
    page = positive(values.get("page"), 1 if submission else None)
    size = (
        positive(values.get("page_size"), 100, maximum=500)
        if submission or "page_size" in values
        else None
    )
    if submission:
        sql = json_object({"sql"})["sql"]
        if not isinstance(sql, str) or not sql.strip():
            raise InvalidRequestError("Invalid request")
        try:
            sql_bytes = len(sql.encode("utf-8"))
        except UnicodeEncodeError:
            raise InvalidRequestError("Invalid request") from None
        if sql_bytes > MAX_SQL_BYTES:
            raise InvalidRequestError("Invalid request")
        return sql, page, size
    return identifier(values.get("query_id")), page, size
