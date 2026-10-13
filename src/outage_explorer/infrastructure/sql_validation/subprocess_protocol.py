"""Bounded parser protocol; no SQL echo or diagnostic text in child output."""

import json
from typing import NoReturn, cast

from outage_explorer.application.ports.sql_inspection import InspectedSql, SqlRejected
from outage_explorer.domain.observations import Grain
from outage_explorer.infrastructure.sql_validation.parser_request import (
    inspect_request as _inspect_request,
)
from outage_explorer.infrastructure.sql_validation.protocol_wire import (
    REQUEST_LIMIT,
    RESPONSE_LIMIT,
    VERSION,
    unique_object,
)

__all__ = [
    "REQUEST_LIMIT",
    "RESPONSE_LIMIT",
    "VERSION",
    "unique_object",
    "decode_scope",
    "inspect_request",
]


def decode_scope(raw: bytes, sql: str) -> InspectedSql:
    response = _decode_response(raw)
    if response.get("status") == "rejected":
        _raise_rejection(response)
    if response.get("status") != "ok":
        raise ValueError("Invalid inspection response")
    if set(response) != {"version", "status", "grains"}:
        raise ValueError("Invalid inspection response")
    scope = _decode_grains(response["grains"])
    return InspectedSql(sql, scope, not scope)


def _decode_response(raw: bytes) -> dict[str, object]:
    if len(raw) > RESPONSE_LIMIT:
        raise ValueError("Inspection response oversized")
    response = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(response, dict) or type(response.get("version")) is not int:
        raise ValueError("Invalid inspection response")
    if response["version"] != VERSION:
        raise ValueError("Invalid inspection version")
    return cast(dict[str, object], response)


def _raise_rejection(response: dict[str, object]) -> NoReturn:
    if set(response) != {"version", "status", "code"}:
        raise ValueError("Invalid inspection rejection")
    code = response.get("code")
    if type(code) is not str or code not in ("invalid_sql", "unsupported_sql"):
        raise ValueError("Invalid inspection rejection")
    raise SqlRejected(code)


def _decode_grains(value: object) -> frozenset[Grain]:
    if not isinstance(value, list) or len(value) > 3:
        raise ValueError("Invalid inspection scope")
    grains: set[Grain] = set()
    for item in value:
        if (
            type(item) is not str
            or item not in ("national", "facility", "generator")
            or item in grains
        ):
            raise ValueError("Invalid inspection scope")
        grains.add(cast(Grain, item))
    return frozenset(grains)


def inspect_request(raw: bytes) -> bytes:
    """Compatibility entry point for the bounded parser child."""
    return _inspect_request(raw)
