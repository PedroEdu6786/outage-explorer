"""Validate canonical worker envelopes and decode preview/query outcomes."""

import json
from datetime import date
from typing import NoReturn

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
from outage_explorer.domain.preview_keys import follows_preview_key
from outage_explorer.infrastructure.query_results.encoding import (
    canonical_json,
    column_descriptors,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    WORKER_PROTOCOL_VERSION,
)
from outage_explorer.infrastructure.worker_runtime.transport_schema import SchemaDecoder
from outage_explorer.infrastructure.worker_runtime.transport_validation import (
    _Invalid,
    _object,
    preview_key,
)
from outage_explorer.infrastructure.worker_runtime.transport_values import ValueDecoder


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise _Invalid()
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise _Invalid()


class ResponseDecoder(ValueDecoder):
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
            self._error(value, request, exit_code)
        _object(value, {"version", "operation", "result"})
        if exit_code != 0 or value["operation"] != (
            "preview" if isinstance(request, PreviewRead) else "query"
        ):
            raise _Invalid()
        if isinstance(request, PreviewRead):
            return self._preview(value["result"], request)
        return self._query(value["result"])

    def _error(
        self, value: dict[str, object], request: PreviewRead | QueryRead, exit_code: int
    ) -> NoReturn:
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
                raise AnalyticalResourceError("Analytical preview deadline exceeded")
            raise AnalyticalTimeoutError("Analytical query deadline exceeded")
        raise RuntimeUnavailableError("Analytical worker unavailable")

    def _preview(self, value: object, request: PreviewRead) -> PreviewRows:
        result = _object(value, {"columns", "rows", "keys", "has_more"})
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
        keys = tuple(preview_key(key, request) for key in result["keys"])
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

    def _query(self, value: object) -> QueryOutput:
        result = _object(
            value,
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
        columns = SchemaDecoder(self.profile).columns(result["columns"])
        rows = self._rows(result["rows"], columns, 1000)
        count, reason = result["retained_row_count"], result["truncation_reason"]
        limits = _object(result["limits"], {"max_rows", "max_bytes"})
        if result["encoding_version"] != "1":
            raise _Invalid()
        if type(count) is not int or count != len(rows):
            raise _Invalid()
        if (
            type(result["truncated"]) is not bool
            or reason not in (None, "row_limit", "byte_limit")
            or result["truncated"] != (reason is not None)
            or (reason == "row_limit" and count != 1000)
        ):
            raise _Invalid()
        if (
            type(limits["max_rows"]) is not int
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
