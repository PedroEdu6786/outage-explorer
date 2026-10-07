"""Strict bounded internal v1 transport; worker output is untrusted input."""

import base64
import json
import math
import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import cast

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    DataUnavailableError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.execution import (
    PreviewRead,
    PreviewRows,
    QueryRead,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.domain.datasets import PUBLIC_DATASETS, Column, ValueType
from outage_explorer.domain.preview_filters import validate_facility_identifier
from outage_explorer.domain.preview_keys import follows_preview_key
from outage_explorer.infrastructure.query_results.encoding import (
    canonical_json,
    column_descriptors,
    encode_cell,
    type_descriptor,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    WORKER_PROTOCOL_VERSION,
    RuntimeProfile,
)


class _Invalid(ValueError):
    pass


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _Invalid()
    return value


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _Invalid()
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise _Invalid()


class WorkerTransport:
    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self.bounds = profile.encoding_bounds

    def request(self, request: PreviewRead | QueryRead) -> bytes:
        """Drop host paths; serialize only approved digest descriptors."""

        total_bytes = 0
        total_files = 0

        def files(values: object) -> list[dict[str, object]]:
            nonlocal total_bytes, total_files
            if (
                not isinstance(values, tuple)
                or not 1 <= len(values) <= self.profile.input_files
            ):
                raise _Invalid()
            result = []
            seen = set()
            total = 0
            for item in values:
                if (
                    re.fullmatch(r"[0-9a-f]{64}", item.sha256) is None
                    or item.sha256 in seen
                    or type(item.byte_count) is not int
                    or not 1 <= item.byte_count <= 2_147_483_647
                    or type(item.rows) is not int
                    or not 1 <= item.rows <= 2_147_483_647
                ):
                    raise _Invalid()
                seen.add(item.sha256)
                total += item.byte_count
                result.append(
                    {
                        "sha256": item.sha256,
                        "byte_count": item.byte_count,
                        "rows": item.rows,
                    }
                )
            total_bytes += total
            total_files += len(result)
            if (
                total_bytes > self.profile.input_bytes
                or total_files > self.profile.input_files
            ):
                raise _Invalid()
            return result

        try:
            payload: dict[str, object]
            if isinstance(request, PreviewRead):
                if (
                    request.dataset not in PUBLIC_DATASETS
                    or type(request.size) is not int
                    or not 1 <= request.size <= 500
                ):
                    raise _Invalid()
                if request.facility is not None:
                    validate_facility_identifier(request.facility)
                    if request.dataset.id == "national":
                        raise _Invalid()
                if any(
                    v is not None and type(v) is not date
                    for v in (request.start, request.end)
                ):
                    raise _Invalid()
                if (
                    request.start is not None
                    and request.end is not None
                    and request.start > request.end
                ):
                    raise _Invalid()
                if request.after is not None:
                    self._key(request.after, request)
                payload = {
                    "version": WORKER_PROTOCOL_VERSION,
                    "operation": "preview",
                    "dataset": request.dataset.id,
                    "files": files(request.files),
                    "start_date": None
                    if request.start is None
                    else request.start.isoformat(),
                    "end_date": None
                    if request.end is None
                    else request.end.isoformat(),
                    "after": request.after,
                    "page_size": request.size,
                    "facility": request.facility,
                }
            else:
                if (
                    not isinstance(request, QueryRead)
                    or not isinstance(request.sql, str)
                    or not request.sql.strip()
                    or len(request.relations) > 3
                ):
                    raise _Invalid()
                seen = set()
                relations = []
                for dataset, approved in request.relations:
                    if dataset not in PUBLIC_DATASETS or dataset.id in seen:
                        raise _Invalid()
                    seen.add(dataset.id)
                    relations.append({"dataset": dataset.id, "files": files(approved)})
                payload = {
                    "version": WORKER_PROTOCOL_VERSION,
                    "operation": "query",
                    "sql": request.sql,
                    "relations": relations,
                }
            raw = canonical_json(payload)
            if len(raw) > self.profile.request_bytes:
                raise _Invalid()
            return raw
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise RuntimeUnavailableError(
                "Invalid analytical worker transport"
            ) from None

    def _parse(self, raw: bytes) -> object:
        if len(raw) > self.profile.stdout_bytes:
            raise _Invalid()
        value: object = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        pending = [(value, 0)]
        count = 0
        while pending:
            item, depth = pending.pop()
            count += 1
            if (
                count > self.profile.json_nodes
                or depth > self.bounds.max_depth * 4 + 12
            ):
                raise _Invalid()
            if isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        if raw not in (canonical_json(value), canonical_json(value) + b"\n"):
            raise _Invalid()
        return value

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
            result = Decimal(value)
            parts = result.as_tuple()
            if (
                not result.is_finite()
                or len(parts.digits) + max(int(parts.exponent), 0)
                > (kind.precision or 0)
                or -int(parts.exponent) > (kind.scale or 0)
            ):
                raise _Invalid()
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
                result = {"key": [k for k, _ in pairs], "value": [v for _, v in pairs]}
            else:
                result = dict(pairs)
                if len(result) != len(pairs):
                    raise _Invalid()
        else:
            raise _Invalid()
        if canonical_json(encode_cell(result, kind, self.bounds)) != canonical_json(
            value
        ):
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

    def _key(self, value: object, request: PreviewRead) -> tuple[str, ...]:
        width = 1 + sum(
            c.name in {"facility", "generator"} for c in request.dataset.columns
        )
        if (
            not isinstance(value, (tuple, list))
            or len(value) != width
            or any(not isinstance(v, str) or not v for v in value)
        ):
            raise _Invalid()
        if date.fromisoformat(value[0]).isoformat() != value[0]:
            raise _Invalid()
        return tuple(value)

    def decode(
        self, raw: bytes, *, request: PreviewRead | QueryRead, exit_code: int
    ) -> PreviewRows | QueryOutput:
        try:
            return self._decode(raw, request, exit_code)
        except SqlRejected:
            raise
        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            UnicodeError,
            OverflowError,
            RecursionError,
        ):
            raise RuntimeUnavailableError(
                "Invalid analytical worker transport"
            ) from None

    def _decode(
        self, raw: bytes, request: PreviewRead | QueryRead, exit_code: int
    ) -> PreviewRows | QueryOutput:
        value = self._parse(raw)
        if (
            not isinstance(value, dict)
            or type(value.get("version")) is not int
            or value["version"] != WORKER_PROTOCOL_VERSION
            or type(exit_code) is not int
        ):
            raise _Invalid()
        if "error" in value:
            _object(value, {"version", "error"})
            error = _object(value["error"], {"code"})
            if exit_code != 1:
                raise _Invalid()
            code = error["code"]
            if code in {"unsupported_sql", "invalid_sql"}:
                raise SqlRejected(code)
            if code == "query_resource_limit":
                raise AnalyticalResourceError("Analytical worker resource limit")
            if code == "data_unavailable":
                raise DataUnavailableError("Analytical inputs unavailable")
            if code == "query_timeout":
                if isinstance(request, PreviewRead):
                    raise AnalyticalResourceError(
                        "Analytical preview deadline exceeded"
                    )
                raise AnalyticalTimeoutError("Analytical query deadline exceeded")
            raise RuntimeUnavailableError("Analytical worker unavailable")
        _object(value, {"version", "operation", "result"})
        if exit_code != 0 or value["operation"] != (
            "preview" if isinstance(request, PreviewRead) else "query"
        ):
            raise _Invalid()
        if isinstance(request, PreviewRead):
            result = _object(value["result"], {"columns", "rows", "keys", "has_more"})
            if canonical_json(result["columns"]) != canonical_json(
                column_descriptors(request.dataset.columns)
            ):
                raise _Invalid()
            rows = self._rows(result["rows"], request.dataset.columns, request.size)
            if (
                not isinstance(result["keys"], list)
                or len(result["keys"]) != len(rows)
                or type(result["has_more"]) is not bool
                or result["has_more"]
                and not rows
            ):
                raise _Invalid()
            keys = tuple(self._key(key, request) for key in result["keys"])
            previous = request.after
            for row, key in zip(rows, keys, strict=True):
                expected = tuple(
                    v.isoformat() if isinstance(v, date) else v
                    for v, c in zip(row, request.dataset.columns, strict=True)
                    if c.name in {"period", "facility", "generator"}
                )
                if key != expected or (
                    previous is not None and not follows_preview_key(key, previous)
                ):
                    raise _Invalid()
                if request.facility is not None and key[1] != request.facility:
                    raise _Invalid()
                day = date.fromisoformat(key[0])
                if (
                    request.start is not None
                    and day < request.start
                    or request.end is not None
                    and day > request.end
                ):
                    raise _Invalid()
                previous = key
            return PreviewRows(rows, keys, result["has_more"])
        result = _object(
            value["result"],
            {
                "encoding_version",
                "columns",
                "rows",
                "retained_row_count",
                "truncated",
                "truncation_reason",
                "limits",
            },
        )
        columns = self._columns(result["columns"])
        rows = self._rows(result["rows"], columns, 1000)
        count, reason = result["retained_row_count"], result["truncation_reason"]
        limits = _object(result["limits"], {"max_rows", "max_bytes"})
        if (
            result["encoding_version"] != "1"
            or type(count) is not int
            or count != len(rows)
            or type(result["truncated"]) is not bool
            or reason not in (None, "row_limit", "byte_limit")
            or result["truncated"] != (reason is not None)
            or reason == "row_limit"
            and count != 1000
            or type(limits["max_rows"]) is not int
            or limits["max_rows"] != 1000
            or type(limits["max_bytes"]) is not int
            or limits["max_bytes"] != 1_048_576
        ):
            raise _Invalid()
        canonical = {
            "encoding_version": "1",
            "columns": column_descriptors(columns),
            "rows": result["rows"],
            "retained_row_count": count,
            "truncated": reason is not None,
            "truncation_reason": reason,
            "limits": {"max_rows": 1000, "max_bytes": 1_048_576},
        }
        document = canonical_json(canonical)
        if (
            document != canonical_json(result)
            or len(document) > self.profile.worker.output_bytes
        ):
            raise _Invalid()
        return QueryOutput(document, count, reason)
