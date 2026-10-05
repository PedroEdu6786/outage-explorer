"""Validate transport inputs and serialize the public identity allowlist."""

import json
from dataclasses import dataclass

from flask import request

from outage_explorer.application.dto import CurrentIdentity
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


@dataclass(frozen=True)
class LoginQuery:
    return_to: str


@dataclass(frozen=True)
class CallbackQuery:
    code: str
    state: str


def login_query() -> LoginQuery:
    values = query_fields(frozenset({"return_to"}))
    return LoginQuery(values.get("return_to", "/"))


def callback_query() -> CallbackQuery:
    values = query_fields(
        frozenset({"code", "state", "error", "error_description", "error_uri"})
    )
    if "error" in values:
        raise UnauthenticatedError("Login failed")
    return CallbackQuery(values.get("code", ""), values.get("state", ""))


def identity_payload(identity: CurrentIdentity) -> dict[str, object]:
    return {
        "user": {
            "id": identity.user.id,
            "email": identity.user.email,
            "role": identity.user.role.value,
        },
        "expires_at": identity.expires_at.isoformat(),
        "csrf_token": identity.csrf_token,
    }
