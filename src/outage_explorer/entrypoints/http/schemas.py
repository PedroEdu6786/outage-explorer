"""Validate transport inputs and serialize the public identity allowlist."""

from flask import request

from outage_explorer.application.dto import CurrentIdentity
from outage_explorer.application.errors import InvalidRequestError


def query_value(name: str, *, default: str = "") -> str:
    values = request.args.getlist(name)
    if len(values) > 1:
        raise InvalidRequestError("Invalid request")
    value = values[0] if values else default
    if (
        len(value) > 4096
        or not value.isascii()
        or any(ord(char) < 32 for char in value)
    ):
        raise InvalidRequestError("Invalid request")
    return value


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
