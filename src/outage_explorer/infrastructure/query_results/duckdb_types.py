"""Map engine metadata without importing/starting DuckDB in the API process."""

from typing import Protocol, cast

from outage_explorer.domain.datasets import ValueType
from outage_explorer.infrastructure.query_results.encoding import UnsupportedValue


class EngineType(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def children(self) -> list[tuple[str, object]]: ...


def value_type(engine_type: EngineType, *, max_depth: int = 16) -> ValueType:
    if max_depth < 0:
        raise UnsupportedValue("Result type nesting is unsupported")
    kind = engine_type.id
    scalar = {
        "boolean": "boolean",
        "varchar": "string",
        "blob": "binary",
        "date": "date",
        "time": "time",
        "timestamp": "timestamp",
        "timestamp_s": "timestamp",
        "timestamp_ms": "timestamp",
        "timestamp with time zone": "timestamp_tz",
        "float": "float",
        "double": "float",
        "null": "null",
        **{
            name: "integer"
            for name in (
                "tinyint",
                "smallint",
                "integer",
                "bigint",
                "hugeint",
                "utinyint",
                "usmallint",
                "uinteger",
                "ubigint",
                "uhugeint",
            )
        },
    }
    if kind in scalar:
        return ValueType(scalar[kind])
    if kind == "decimal":
        attrs = dict(engine_type.children)
        return ValueType(
            "decimal",
            int(cast(int, attrs["precision"])),
            int(cast(int, attrs["scale"])),
        )
    if kind in ("list", "struct", "map"):
        return ValueType(
            kind,
            children=tuple(
                (name, value_type(cast(EngineType, child), max_depth=max_depth - 1))
                for name, child in engine_type.children
            ),
        )
    # Python datetime drops nanoseconds; interval loses calendar months. Refuse
    # rather than advertise a lossless encoding for these engine conversions.
    raise UnsupportedValue("Unsupported result type")
