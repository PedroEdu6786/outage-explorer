"""Validate authentication transport inputs."""

import json
from collections.abc import Callable

from flask import request
from pydantic import BaseModel, ConfigDict

from outage_explorer.application.errors import InvalidRequestError, UnauthenticatedError


def query_value(name: str, *, default: str = "") -> str:
    values = request.args.getlist(name)
    if len(values) > 1:
        raise InvalidRequestError("Invalid request")
    value = values[0] if values else default
    if (
        len(value) > 4096
        or not value.isascii()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise InvalidRequestError("Invalid request")
    return value


def query_fields(
    allowed: frozenset[str], *, required: frozenset[str] = frozenset()
) -> dict[str, str]:
    """Return scalar transport values; schema callers own their value types."""
    if request.args.keys() - allowed or required - request.args.keys():
        raise InvalidRequestError("Invalid request")
    return {name: query_value(name) for name in request.args}


def json_object(
    allowed: frozenset[str], *, required: frozenset[str] = frozenset()
) -> dict[str, object]:
    """Read a bounded JSON object, rejecting ambiguous fields and non-JSON values."""
    if not request.is_json or (
        request.content_length is not None and request.content_length > 65536
    ):
        raise InvalidRequestError("Invalid request")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid_constant(value: str) -> object:
        raise ValueError

    try:
        body = request.stream.read(65537)
        if len(body) > 65536:
            raise ValueError
        decoded: object = json.loads(
            body.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=invalid_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidRequestError("Invalid request") from None
    if (
        not isinstance(decoded, dict)
        or decoded.keys() - allowed
        or required - decoded.keys()
    ):
        raise InvalidRequestError("Invalid request")
    return {str(key): value for key, value in decoded.items()}


class LoginQuery(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    return_to: str


class CallbackQuery(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    code: str
    state: str
    browser_binding: str = ""


def login_query() -> LoginQuery:
    values = query_fields(frozenset({"return_to"}))
    return LoginQuery(return_to=values.get("return_to", "/"))


def callback_query(*, binding: Callable[[], str] | None = None) -> CallbackQuery:
    values = query_fields(
        frozenset({"code", "state", "error", "error_description", "error_uri"})
    )
    if "error" in values:
        raise UnauthenticatedError("Login failed")
    return CallbackQuery(
        code=values.get("code", ""),
        state=values.get("state", ""),
        browser_binding="" if binding is None else binding(),
    )
