"""Bounded parser protocol; no SQL echo or diagnostic text in child output."""

import json
from typing import cast

from outage_explorer.application.ports.sql_inspection import InspectedSql, SqlRejected
from outage_explorer.domain.observations import Grain

VERSION = 1
REQUEST_LIMIT = 6 * 65_536 + 1024
RESPONSE_LIMIT = 1024


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate inspection field")
        result[key] = value
    return result


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
    grains = value["grains"]
    if (
        not isinstance(grains, list)
        or len(grains) > 3
        or any(
            type(g) is not str or g not in ("national", "facility", "generator")
            for g in grains
        )
        or len(set(grains)) != len(grains)
    ):
        raise ValueError("Invalid inspection scope")
    scope = frozenset(cast(Grain, g) for g in grains)
    return InspectedSql(sql, scope, not scope)


def inspect_request(raw: bytes) -> bytes:
    """Called only by the limited child; imports parser after launcher limits."""
    from outage_explorer.infrastructure.sql_validation.inspection import (
        DuckdbSqlInspector,
    )

    try:
        if len(raw) > REQUEST_LIMIT:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=unique_object)
        if (
            not isinstance(value, dict)
            or set(value)
            != {"version", "sql", "max_sql_bytes", "max_nodes", "max_depth"}
            or type(value["version"]) is not int
            or value["version"] != VERSION
            or type(value["sql"]) is not str
        ):
            raise ValueError
        for key, ceiling in (
            ("max_sql_bytes", 65_536),
            ("max_nodes", 10_000),
            ("max_depth", 64),
        ):
            if type(value[key]) is not int or not 1 <= value[key] <= ceiling:
                raise ValueError
        inspected = DuckdbSqlInspector(
            max_sql_bytes=value["max_sql_bytes"],
            max_nodes=value["max_nodes"],
            max_depth=value["max_depth"],
        ).inspect(value["sql"])
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
