"""Bounded parser protocol; no SQL echo or diagnostic text in child output."""

import json
from typing import cast

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
    if len(raw) > RESPONSE_LIMIT:
        raise ValueError("Inspection response oversized")
    value = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(value, dict) or type(value.get("version")) is not int:
        raise ValueError("Invalid inspection response")
    if value["version"] != VERSION:
        raise ValueError("Invalid inspection version")
    if value.get("status") == "rejected":
        if set(value) != {"version", "status", "code"} or value["code"] not in (
            "invalid_sql",
            "unsupported_sql",
        ):
            raise ValueError("Invalid inspection rejection")
        raise SqlRejected(value["code"])
    if set(value) != {"version", "status", "grains"} or value["status"] != "ok":
        raise ValueError("Invalid inspection response")
    scope = _decode_grains(value["grains"])
    return InspectedSql(sql, scope, not scope)


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
