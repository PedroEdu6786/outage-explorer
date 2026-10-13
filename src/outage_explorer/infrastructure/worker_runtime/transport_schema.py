"""Decode bounded column and type schemas from worker responses."""

from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import (
    canonical_json,
    type_descriptor,
)
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.transport_validation import (
    _Invalid,
    _object,
)


class SchemaDecoder:
    def __init__(self, profile: RuntimeProfile) -> None:
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
            precision, scale = self._decimal_parts(value)
            fields.update({"precision", "scale"})
        if kind in {"list", "map", "struct"}:
            children = self._children(value, kind, depth)
            if children:
                fields.add("children")
        _object(value, fields)
        result = ValueType(kind, precision, scale, children)
        if value != type_descriptor(result):
            raise _Invalid()
        return result

    def _decimal_parts(self, value: dict[str, object]) -> tuple[int, int]:
        precision, scale = value.get("precision"), value.get("scale")
        if (
            type(precision) is not int
            or type(scale) is not int
            or not 0 <= scale <= precision <= 38
        ):
            raise _Invalid()
        return precision, scale

    def _children(
        self, value: dict[str, object], kind: str, depth: int
    ) -> tuple[tuple[str, ValueType], ...]:
        values = value.get("children", [])
        if not isinstance(values, list) or len(values) > self.bounds.max_nested_items:
            raise _Invalid()
        children = []
        for child in values:
            if not isinstance(child, dict) or not isinstance(child.get("name"), str):
                raise _Invalid()
            child_type = self._type(
                {key: item for key, item in child.items() if key != "name"}, depth + 1
            )
            children.append((child["name"], child_type))
        if kind == "list" and len(children) != 1:
            raise _Invalid()
        if kind == "map" and len(children) != 2:
            raise _Invalid()
        if kind == "struct" and len({name for name, _ in children}) != len(children):
            raise _Invalid()
        return tuple(children)

    def columns(self, value: object) -> tuple[Column, ...]:
        if (
            not isinstance(value, list)
            or len(value) > self.bounds.max_columns
            or len(canonical_json(value)) > self.bounds.max_schema_bytes
        ):
            raise _Invalid()
        return tuple(self._column(raw, index) for index, raw in enumerate(value))

    def _column(self, raw: object, index: int) -> Column:
        if not isinstance(raw, dict) or type(raw.get("index")) is not int:
            raise _Invalid()
        if raw["index"] != index:
            raise _Invalid()
        name = raw.get("name")
        if not isinstance(name, str) or not {"nullable", "unit"} <= set(raw):
            raise _Invalid()
        nullable, unit = raw["nullable"], raw["unit"]
        if nullable is not None and type(nullable) is not bool:
            raise _Invalid()
        if unit is not None and not isinstance(unit, str):
            raise _Invalid()
        descriptor = {
            key: item
            for key, item in raw.items()
            if key not in {"index", "name", "nullable", "unit"}
        }
        return Column(name, self._type(descriptor), nullable, unit)
