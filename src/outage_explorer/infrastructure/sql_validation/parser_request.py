"""Validate one bounded parser-child request and encode its response."""

import json
from dataclasses import dataclass

from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.sql_validation.protocol_wire import (
    REQUEST_LIMIT,
    VERSION,
    unique_object,
)

_FIELDS = {"version", "sql", "max_sql_bytes", "max_nodes", "max_depth"}
_MAX_SQL_BYTES = 65_536
_MAX_NODES = 10_000
_MAX_DEPTH = 64


@dataclass(frozen=True)
class ParserRequest:
    sql: str
    max_sql_bytes: int
    max_nodes: int
    max_depth: int

    @classmethod
    def decode(cls, raw: bytes) -> "ParserRequest":
        if len(raw) > REQUEST_LIMIT:
            raise ValueError("Inspection request oversized")
        value = json.loads(raw, object_pairs_hook=unique_object)
        if (
            not isinstance(value, dict)
            or set(value) != _FIELDS
            or type(value["version"]) is not int
            or value["version"] != VERSION
            or type(value["sql"]) is not str
        ):
            raise ValueError("Invalid inspection request")
        for field, ceiling in (
            ("max_sql_bytes", _MAX_SQL_BYTES),
            ("max_nodes", _MAX_NODES),
            ("max_depth", _MAX_DEPTH),
        ):
            if type(value[field]) is not int or not 1 <= value[field] <= ceiling:
                raise ValueError("Invalid inspection bound")
        return cls(
            value["sql"], value["max_sql_bytes"], value["max_nodes"], value["max_depth"]
        )


def inspect_request(raw: bytes) -> bytes:
    """Called only by the limited child; load the parser after request validation."""
    try:
        request = ParserRequest.decode(raw)
        from outage_explorer.infrastructure.sql_validation.inspection import (
            DuckdbSqlInspector,
        )

        inspected = DuckdbSqlInspector(
            max_sql_bytes=request.max_sql_bytes,
            max_nodes=request.max_nodes,
            max_depth=request.max_depth,
        ).inspect(request.sql)
        response = {
            "version": VERSION,
            "status": "ok",
            "grains": sorted(inspected.grains),
        }
    except SqlRejected as error:
        response = {"version": VERSION, "status": "rejected", "code": error.code}
    except (ValueError, TypeError, UnicodeError, RecursionError):
        response = {"version": VERSION, "status": "rejected", "code": "invalid_sql"}
    return json.dumps(response, separators=(",", ":")).encode("ascii")
