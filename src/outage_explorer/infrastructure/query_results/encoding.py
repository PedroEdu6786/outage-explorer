"""Canonical v1 UTF-8 representation with explicit scratch/depth bounds."""

import base64
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from outage_explorer.domain.datasets import Column, ValueType


class EncodingLimit(ValueError):
    """Safe resource failure (query_resource_limit)."""


class EncodingCellLimit(EncodingLimit):
    """A single cell exceeds the bounded byte scratch capacity."""


class UnsupportedValue(ValueError):
    """No implicit string conversion or precision loss is permitted."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


_ENCODINGS = {
    "integer": "integer-string",
    "decimal": "decimal-string",
    "float": "number-or-special-string",
    "boolean": "boolean",
    "string": "string",
    "date": "iso-date",
    "time": "iso-time",
    "timestamp": "iso-local-datetime",
    "timestamp_tz": "iso-utc-datetime",
    "binary": "base64",
    "list": "array",
    "struct": "field-array",
    "map": "pair-array",
    "null": "null",
}


def type_descriptor(value_type: ValueType) -> dict[str, object]:
    try:
        result: dict[str, object] = {
            "type": value_type.kind,
            "encoding": _ENCODINGS[value_type.kind],
        }
    except KeyError as exc:
        raise UnsupportedValue("Unsupported result type") from exc
    if value_type.kind == "decimal":
        result.update(precision=value_type.precision, scale=value_type.scale)
    if value_type.children:
        result["children"] = [
            {"name": name, **type_descriptor(child)}
            for name, child in value_type.children
        ]
    return result


def column_descriptors(columns: Sequence[Column]) -> list[dict[str, object]]:
    return [
        {
            "index": i,
            "name": col.name,
            **type_descriptor(col.value_type),
            "nullable": col.nullable,
            "unit": col.unit,
        }
        for i, col in enumerate(columns)
    ]


@dataclass(frozen=True)
class EncodingBounds:
    max_cell_bytes: int
    max_depth: int
    max_nested_items: int
    max_columns: int
    max_schema_bytes: int

    def __post_init__(self) -> None:
        if min(vars(self).values()) <= 0:
            raise ValueError("Encoding bounds must be positive")


def encode_cell(value: object, value_type: ValueType, bounds: EncodingBounds) -> object:
    remaining = [bounds.max_nested_items]
    remaining_bytes = [bounds.max_cell_bytes]

    def charge(size: int) -> None:
        remaining_bytes[0] -= size
        if remaining_bytes[0] < 0:
            raise EncodingCellLimit("Cell exceeds encoding bounds")

    def encode(item: object, kind: ValueType, depth: int) -> object:
        remaining[0] -= 1
        if depth > bounds.max_depth or remaining[0] < 0:
            raise EncodingLimit("Nested value exceeds encoding bounds")
        if item is None:
            charge(4)
            return None
        result: object
        if kind.kind == "integer" and type(item) is int:
            if item.bit_length() > bounds.max_cell_bytes * 3:
                raise EncodingCellLimit("Cell exceeds encoding bounds")
            result = str(item)
        elif kind.kind == "decimal" and isinstance(item, Decimal) and item.is_finite():
            parts = item.as_tuple()
            if len(parts.digits) + abs(int(parts.exponent)) + 3 > bounds.max_cell_bytes:
                raise EncodingCellLimit("Cell exceeds encoding bounds")
            result = format(item, "f")
        elif kind.kind == "float" and type(item) is float:
            result = (
                item
                if math.isfinite(item)
                else "NaN"
                if math.isnan(item)
                else "Infinity"
                if item > 0
                else "-Infinity"
            )
        elif kind.kind == "boolean" and type(item) is bool:
            result = item
        elif kind.kind == "string" and type(item) is str:
            if len(item) > bounds.max_cell_bytes:
                raise EncodingCellLimit("Cell exceeds encoding bounds")
            result = item
        elif kind.kind == "date" and type(item) is date:
            # DuckDB maps +/-infinity to these same finite Python sentinels.
            # Refuse ambiguous extremes rather than silently misrepresent them.
            if item in (date.min, date.max):
                raise UnsupportedValue("Ambiguous temporal extreme")
            result = item.isoformat()
        elif kind.kind == "time" and type(item) is time and item.tzinfo is None:
            result = item.isoformat()
        elif (
            kind.kind == "timestamp" and type(item) is datetime and item.tzinfo is None
        ):
            if item in (datetime.min, datetime.max):
                raise UnsupportedValue("Ambiguous temporal extreme")
            result = item.isoformat()
        elif (
            kind.kind == "timestamp_tz"
            and type(item) is datetime
            and item.utcoffset() is not None
        ):
            if item.replace(tzinfo=None) in (datetime.min, datetime.max):
                raise UnsupportedValue("Ambiguous temporal extreme")
            result = item.astimezone(UTC).isoformat().replace("+00:00", "Z")
        elif kind.kind == "binary" and type(item) is bytes:
            if len(item) * 4 // 3 > bounds.max_cell_bytes:
                raise EncodingCellLimit("Cell exceeds encoding bounds")
            result = base64.b64encode(item).decode("ascii")
        elif (
            kind.kind == "list"
            and isinstance(item, (list, tuple))
            and len(kind.children) == 1
        ):
            charge(2 + max(0, len(item) - 1))
            result = [encode(child, kind.children[0][1], depth + 1) for child in item]
        elif (
            kind.kind == "struct"
            and isinstance(item, dict)
            and set(item) == {name for name, _ in kind.children}
        ):
            charge(2 + max(0, len(kind.children) - 1))
            result = [
                encode(item[name], child, depth + 1) for name, child in kind.children
            ]
        elif kind.kind == "map" and isinstance(item, dict) and len(kind.children) == 2:
            pairs: Iterable[tuple[object, object]]
            if kind.children[0][1].kind in ("list", "struct", "map"):
                # DuckDB uses parallel key/value arrays for unhashable keys.
                keys, values = item.get("key"), item.get("value")
                if (
                    set(item) != {"key", "value"}
                    or not isinstance(keys, list)
                    or not isinstance(values, list)
                    or len(keys) != len(values)
                ):
                    raise UnsupportedValue("Unsupported map value")
                count = len(keys)
                pairs = zip(keys, values, strict=True)
            else:
                count = len(item)
                pairs = item.items()
            charge(2 + max(0, count - 1) + 3 * count)
            result = [
                [
                    encode(key, kind.children[0][1], depth + 1),
                    encode(val, kind.children[1][1], depth + 1),
                ]
                for key, val in pairs
            ]
        else:
            raise UnsupportedValue("Unsupported result value")
        if kind.kind not in ("list", "struct", "map"):
            charge(len(canonical_json(result)))
        return result

    try:
        return encode(value, value_type, 0)
    except (UnicodeError, OverflowError) as exc:
        raise UnsupportedValue("Unsupported result value") from exc


def _validate_schema(columns: Sequence[Column], bounds: EncodingBounds) -> None:
    remaining = bounds.max_nested_items
    pending = [(column.value_type, 0) for column in columns]
    name_bytes = 0
    for column in columns:
        if len(column.name) > bounds.max_schema_bytes:
            raise EncodingLimit("Schema exceeds encoding bounds")
        name_bytes += len(column.name.encode("utf-8"))
    while pending:
        kind, depth = pending.pop()
        remaining -= 1
        if (
            remaining < 0
            or depth > bounds.max_depth
            or name_bytes > bounds.max_schema_bytes
        ):
            raise EncodingLimit("Schema exceeds encoding bounds")
        if kind.kind not in _ENCODINGS:
            raise UnsupportedValue("Unsupported result type")
        if kind.kind == "decimal":
            if (
                kind.precision is None
                or kind.scale is None
                or not 0 <= kind.scale <= kind.precision <= 38
            ):
                raise UnsupportedValue("Invalid decimal type")
        elif kind.precision is not None or kind.scale is not None:
            raise UnsupportedValue("Invalid result type")
        if (
            kind.kind == "list"
            and len(kind.children) != 1
            or kind.kind == "map"
            and len(kind.children) != 2
        ):
            raise UnsupportedValue("Invalid nested type")
        if kind.kind not in ("list", "struct", "map") and kind.children:
            raise UnsupportedValue("Invalid result type")
        if len(kind.children) > remaining:
            raise EncodingLimit("Schema exceeds encoding bounds")
        for name, child in kind.children:
            if len(name) > bounds.max_schema_bytes:
                raise EncodingLimit("Schema exceeds encoding bounds")
            name_bytes += len(name.encode("utf-8"))
            pending.append((child, depth + 1))


@dataclass(frozen=True)
class EncodedResult:
    document: bytes
    retained_row_count: int
    truncation_reason: str | None


def retain_result(
    columns: Sequence[Column],
    rows: Iterable[Sequence[object]],
    bounds: EncodingBounds,
    *,
    max_rows: int = 1000,
    max_bytes: int = 1_048_576,
) -> EncodedResult:
    """Consume a complete-row prefix and at most one row of lookahead.

    Reserves worst-case fixed metadata up front; bytes contain metadata once.
    Input acquisition/engine memory and the later HTTP envelope need their own bounds.
    """
    if not 0 < max_rows <= 1000 or not 0 < max_bytes <= 1_048_576:
        raise ValueError("Result limits exceed the accepted bounds")
    if len(columns) > bounds.max_columns:
        raise EncodingLimit("Schema exceeds encoding bounds")
    _validate_schema(columns, bounds)
    descriptors = column_descriptors(columns)
    if len(canonical_json(descriptors)) > bounds.max_schema_bytes:
        raise EncodingLimit("Schema exceeds encoding bounds")

    def document(count: int, reason: str | None, retained: list[list[object]]) -> bytes:
        return canonical_json(
            {
                "encoding_version": "1",
                "columns": descriptors,
                "rows": retained,
                "retained_row_count": count,
                "truncated": reason is not None,
                "truncation_reason": reason,
                "limits": {"max_rows": max_rows, "max_bytes": max_bytes},
            }
        )

    # 'false' is one byte longer than 'true'; reserve it as well.
    used = len(document(max_rows, "byte_limit", [])) + 1
    if used > max_bytes:
        raise EncodingLimit("Schema and metadata exceed result capacity")
    retained: list[list[object]] = []
    reason: str | None = None
    for row in rows:
        if len(retained) == max_rows:
            reason = "row_limit"
            break
        if len(row) != len(columns):
            raise UnsupportedValue("Row does not match columns")
        if any(
            value is None and col.nullable is False
            for value, col in zip(row, columns, strict=True)
        ):
            raise UnsupportedValue("Null in a non-nullable column")
        encoded: list[object] = []
        size = 2 + bool(retained)
        for value, col in zip(row, columns, strict=True):
            try:
                cell = encode_cell(value, col.value_type, bounds)
            except EncodingCellLimit:
                # When scratch can cover the entire accepted document, an
                # over-scratch cell cannot fit this row. Preserve the prefix.
                if bounds.max_cell_bytes < max_bytes:
                    raise
                size = max_bytes + 1
                break
            size += len(canonical_json(cell)) + bool(encoded)
            if used + size > max_bytes:
                break
            encoded.append(cell)
        if used + size > max_bytes:
            reason = "byte_limit"
            break
        retained.append(encoded)
        used += size
    return EncodedResult(
        document(len(retained), reason, retained), len(retained), reason
    )
