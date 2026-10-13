"""Decode bounded query schemas and cell values from worker responses."""

import base64
import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import cast

from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import (
    canonical_json,
    encode_cell,
    type_descriptor,
)
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.transport_validation import (
    _Invalid,
    _object,
)


class ValueDecoder:
    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self.bounds = profile.encoding_bounds

    def _type(self, value: dict[str, object], depth: int = 0) -> ValueType:
        if depth > self.bounds.max_depth:
            raise _Invalid()
        kind = value.get("type")
        if not isinstance(kind, str):
            raise _Invalid()
        fields = {"type", "encoding"}
        precision = scale = None
        children: tuple[tuple[str, ValueType], ...] = ()
        if kind == "decimal":
            fields |= {"precision", "scale"}
            precision, scale = value.get("precision"), value.get("scale")
            if (
                type(precision) is not int
                or type(scale) is not int
                or not 0 <= scale <= precision <= 38
            ):
                raise _Invalid()
        if kind in {"list", "map", "struct"}:
            values = value.get("children", [])
            if (
                not isinstance(values, list)
                or len(values) > self.bounds.max_nested_items
            ):
                raise _Invalid()
            if values:
                fields.add("children")
            parsed = []
            for child in values:
                if not isinstance(child, dict) or not isinstance(
                    child.get("name"), str
                ):
                    raise _Invalid()
                parsed.append(
                    (
                        child["name"],
                        self._type(
                            {k: v for k, v in child.items() if k != "name"}, depth + 1
                        ),
                    )
                )
            children = tuple(parsed)
            if (
                kind == "list"
                and len(children) != 1
                or kind == "map"
                and len(children) != 2
            ):
                raise _Invalid()
            if kind == "struct" and len({n for n, _ in children}) != len(children):
                raise _Invalid()
        _object(value, fields)
        result = ValueType(
            kind, cast(int | None, precision), cast(int | None, scale), children
        )
        if value != type_descriptor(result):
            raise _Invalid()
        return result

    def _columns(self, value: object) -> tuple[Column, ...]:
        if (
            not isinstance(value, list)
            or len(value) > self.bounds.max_columns
            or len(canonical_json(value)) > self.bounds.max_schema_bytes
        ):
            raise _Invalid()
        columns = []
        for index, raw in enumerate(value):
            if (
                not isinstance(raw, dict)
                or type(raw.get("index")) is not int
                or raw["index"] != index
                or not isinstance(raw.get("name"), str)
            ):
                raise _Invalid()
            if (
                not {"nullable", "unit"} <= set(raw)
                or raw["nullable"] is not None
                and type(raw["nullable"]) is not bool
                or raw["unit"] is not None
                and not isinstance(raw["unit"], str)
            ):
                raise _Invalid()
            kind = self._type(
                {
                    k: v
                    for k, v in raw.items()
                    if k not in {"index", "name", "nullable", "unit"}
                }
            )
            columns.append(Column(raw["name"], kind, raw["nullable"], raw["unit"]))
        return tuple(columns)

    def _cell(self, value: object, kind: ValueType, depth: int = 0) -> object:
        if (
            depth > self.bounds.max_depth
            or len(canonical_json(value)) > self.bounds.max_cell_bytes
        ):
            raise _Invalid()
        if value is None:
            return None
        result: object
        if (
            kind.kind == "integer"
            and isinstance(value, str)
            and re.fullmatch(r"-?(0|[1-9][0-9]*)", value)
        ):
            result = int(value)
        elif (
            kind.kind == "decimal"
            and isinstance(value, str)
            and re.fullmatch(r"-?(0|[1-9][0-9]*)(\.[0-9]+)?", value)
        ):
            result = self._decimal(value, kind)
        elif kind.kind == "float" and type(value) is float and math.isfinite(value):
            result = value
        elif kind.kind == "float" and value in ("NaN", "Infinity", "-Infinity"):
            result = float(value)
        elif kind.kind == "boolean" and type(value) is bool:
            result = value
        elif kind.kind == "string" and isinstance(value, str):
            result = value
        elif kind.kind == "date" and isinstance(value, str):
            result = date.fromisoformat(value)
        elif kind.kind == "time" and isinstance(value, str):
            result = time.fromisoformat(value)
        elif kind.kind in {"timestamp", "timestamp_tz"} and isinstance(value, str):
            result = datetime.fromisoformat(value)
        elif kind.kind == "binary" and isinstance(value, str):
            result = base64.b64decode(value, validate=True)
        elif kind.kind == "list" and isinstance(value, list):
            result = [self._cell(v, kind.children[0][1], depth + 1) for v in value]
        elif (
            kind.kind == "struct"
            and isinstance(value, list)
            and len(value) == len(kind.children)
        ):
            result = {
                n: self._cell(v, t, depth + 1)
                for v, (n, t) in zip(value, kind.children, strict=True)
            }
        elif kind.kind == "map" and isinstance(value, list):
            result = self._map(value, kind, depth)
        else:
            raise _Invalid()
        if canonical_json(encode_cell(result, kind, self.bounds)) != canonical_json(
            value
        ):
            raise _Invalid()
        return result

    def _decimal(self, value: str, kind: ValueType) -> Decimal:
        result = Decimal(value)
        parts = result.as_tuple()
        if (
            not result.is_finite()
            or len(parts.digits) + max(int(parts.exponent), 0) > (kind.precision or 0)
            or -int(parts.exponent) > (kind.scale or 0)
        ):
            raise _Invalid()
        return result

    def _map(self, value: list[object], kind: ValueType, depth: int) -> object:
        pairs = []
        for pair in value:
            if not isinstance(pair, list) or len(pair) != 2:
                raise _Invalid()
            pairs.append(
                (
                    self._cell(pair[0], kind.children[0][1], depth + 1),
                    self._cell(pair[1], kind.children[1][1], depth + 1),
                )
            )
        if kind.children[0][1].kind in {"list", "map", "struct"}:
            return {"key": [k for k, _ in pairs], "value": [v for _, v in pairs]}
        result = dict(pairs)
        if len(result) != len(pairs):
            raise _Invalid()
        return result

    def _rows(
        self, value: object, columns: tuple[Column, ...], maximum: int
    ) -> tuple[tuple[object, ...], ...]:
        if not isinstance(value, list) or len(value) > maximum:
            raise _Invalid()
        rows = []
        for row in value:
            if not isinstance(row, list) or len(row) != len(columns):
                raise _Invalid()
            if any(
                v is None and c.nullable is False
                for v, c in zip(row, columns, strict=True)
            ):
                raise _Invalid()
            rows.append(
                tuple(
                    self._cell(v, c.value_type)
                    for v, c in zip(row, columns, strict=True)
                )
            )
        return tuple(rows)
