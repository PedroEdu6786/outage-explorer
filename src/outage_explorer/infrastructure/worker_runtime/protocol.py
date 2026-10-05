"""One bounded internal request; caller owns authorization and OS isolation."""

import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
    InvalidRequestError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.execution import (
    PreviewRead,
    PreviewRows,
    QueryRead,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.application.ports.sql_inspection import SqlInspector, SqlRejected
from outage_explorer.domain.datasets import PUBLIC_DATASETS, Dataset
from outage_explorer.infrastructure.query_results.encoding import canonical_json
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)

MAX_REQUEST_BYTES = 131_072
MAX_RESPONSE_BYTES = 1_048_576 + 131_072


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidRequestError("Invalid worker request")
    return value


def _positive(value: object, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise InvalidRequestError("Invalid worker request")
    return value


def _day(value: object) -> date | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError("Invalid worker request")
    result = date.fromisoformat(value)
    if result.isoformat() != value:
        raise InvalidRequestError("Invalid worker request")
    return result


def _dataset(value: object) -> Dataset:
    for dataset in PUBLIC_DATASETS:
        if value == dataset.id:
            return dataset
    raise InvalidRequestError("Invalid worker request")


class AnalyticalWorker:
    def __init__(
        self,
        inputs_root: Path,
        preview: Callable[[PreviewRead], PreviewRows],
        query: Callable[[QueryRead], QueryOutput],
        inspector: SqlInspector,
        encoding: PreviewEncoding,
    ) -> None:
        self._root, self._preview, self._query = inputs_root, preview, query
        self._inspector, self._encoding = inspector, encoding

    def _files(self, value: object) -> tuple[ApprovedFile, ...]:
        if not isinstance(value, list) or not 1 <= len(value) <= 10_000:
            raise InvalidRequestError("Invalid worker request")
        files = []
        seen: set[str] = set()
        for item in value:
            fields = _object(item, {"sha256", "byte_count", "rows"})
            digest = fields["sha256"]
            if (
                not isinstance(digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                or digest in seen
            ):
                raise InvalidRequestError("Invalid worker request")
            seen.add(digest)
            files.append(
                ApprovedFile(
                    str(self._root / (digest + ".parquet")),
                    digest,
                    _positive(fields["byte_count"], 2_147_483_647),
                    _positive(fields["rows"], 2_147_483_647),
                )
            )
        return tuple(files)

    def _execute(self, raw: bytes) -> dict[str, object]:
        if len(raw) > MAX_REQUEST_BYTES:
            raise InvalidRequestError("Invalid worker request")

        def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in items:
                if key in result:
                    raise InvalidRequestError("Invalid worker request")
                result[key] = value
            return result

        def constant(value: str) -> object:
            raise InvalidRequestError("Invalid worker request")

        payload: object = json.loads(
            raw, object_pairs_hook=pairs, parse_constant=constant
        )
        if not isinstance(payload, dict) or type(payload.get("version")) is not int:
            raise InvalidRequestError("Invalid worker request")
        if payload["version"] != 1:
            raise InvalidRequestError("Invalid worker request")
        operation = payload.get("operation")
        if operation == "preview":
            fields = _object(
                payload,
                {
                    "version",
                    "operation",
                    "dataset",
                    "files",
                    "start_date",
                    "end_date",
                    "after",
                    "page_size",
                },
            )
            dataset = _dataset(fields["dataset"])
            start, end = _day(fields["start_date"]), _day(fields["end_date"])
            if start is not None and end is not None and start > end:
                raise InvalidRequestError("Invalid worker request")
            after = fields["after"]
            if after is not None:
                key_size = 1 + sum(
                    column.name in {"facility", "generator"}
                    for column in dataset.columns
                )
                if (
                    not isinstance(after, list)
                    or len(after) != key_size
                    or any(not isinstance(item, str) for item in after)
                ):
                    raise InvalidRequestError("Invalid worker request")
                _day(after[0])
            read = PreviewRead(
                dataset,
                self._files(fields["files"]),
                start,
                end,
                None if after is None else tuple(after),
                _positive(fields["page_size"], 500),
            )
            preview = self._preview(read)
            return {
                "version": 1,
                "operation": operation,
                "result": {
                    "columns": self._encoding.columns(dataset.columns),
                    "rows": [
                        self._encoding.row(dataset.columns, row) for row in preview.rows
                    ],
                    "keys": preview.keys,
                    "has_more": preview.has_more,
                },
            }
        if operation == "query":
            fields = _object(payload, {"version", "operation", "sql", "relations"})
            sql = fields["sql"]
            relations = fields["relations"]
            if (
                not isinstance(sql, str)
                or not sql.strip()
                or not isinstance(relations, list)
                or len(relations) > 3
            ):
                raise InvalidRequestError("Invalid worker request")
            inspected = self._inspector.inspect(sql)
            approved = []
            seen = set()
            for value in relations:
                relation = _object(value, {"dataset", "files"})
                dataset = _dataset(relation["dataset"])
                if dataset.id in seen:
                    raise InvalidRequestError("Invalid worker request")
                seen.add(dataset.id)
                approved.append((dataset, self._files(relation["files"])))
            if inspected.grains != frozenset(dataset.grain for dataset, _ in approved):
                raise InvalidRequestError("Invalid worker request")
            output = self._query(QueryRead(sql, tuple(approved)))
            if len(output.document) > 1_048_576:
                raise AnalyticalResourceError("Worker output limit")
            return {
                "version": 1,
                "operation": operation,
                "result": json.loads(output.document),
            }
        raise InvalidRequestError("Invalid worker request")

    def execute(self, raw: bytes) -> bytes:
        try:
            response = canonical_json(self._execute(raw))
            if len(response) > MAX_RESPONSE_BYTES:
                raise AnalyticalResourceError("Worker output limit")
            return response
        except SqlRejected as error:
            code = error.code
        except (InvalidRequestError, ValueError, UnicodeError, RecursionError):
            code = "invalid_request"
        except AnalyticalResourceError:
            code = "query_resource_limit"
        except DataUnavailableError:
            code = "data_unavailable"
        except Exception:
            code = "worker_execution_failed"
        return canonical_json({"version": 1, "error": {"code": code}})
