"""Encode approved analytical inputs without exposing host paths."""

import re
from datetime import date

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.application.ports.execution import PreviewRead, QueryRead
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.preview_filters import validate_facility_identifier
from outage_explorer.infrastructure.query_results.encoding import canonical_json
from outage_explorer.infrastructure.worker_runtime.configuration import (
    WORKER_PROTOCOL_VERSION,
    RuntimeProfile,
)
from outage_explorer.infrastructure.worker_runtime.transport_validation import (
    _Invalid,
    preview_key,
)


class _FileBudget:
    """Track file and byte limits across all query relations."""

    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile
        self.total_bytes = 0
        self.total_files = 0

    def add(self, values: object) -> list[dict[str, object]]:
        if (
            not isinstance(values, tuple)
            or not 1 <= len(values) <= self.profile.input_files
        ):
            raise _Invalid()
        result = []
        seen = set()
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
            self.total_bytes += item.byte_count
            self.total_files += 1
            result.append(
                {
                    "sha256": item.sha256,
                    "byte_count": item.byte_count,
                    "rows": item.rows,
                }
            )
        if (
            self.total_bytes > self.profile.input_bytes
            or self.total_files > self.profile.input_files
        ):
            raise _Invalid()
        return result


class RequestEncoder:
    def __init__(self, profile: RuntimeProfile) -> None:
        self.profile = profile

    def request(self, request: PreviewRead | QueryRead) -> bytes:
        try:
            files = _FileBudget(self.profile)
            if isinstance(request, PreviewRead):
                payload = self._preview(request, files)
            elif isinstance(request, QueryRead):
                payload = self._query(request, files)
            else:
                raise _Invalid()
            raw = canonical_json(payload)
            if len(raw) > self.profile.request_bytes:
                raise _Invalid()
            return raw
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise RuntimeUnavailableError(
                "Invalid analytical worker transport"
            ) from None

    def _preview(self, request: PreviewRead, files: _FileBudget) -> dict[str, object]:
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
            value is not None and type(value) is not date
            for value in (request.start, request.end)
        ):
            raise _Invalid()
        if (
            request.start is not None
            and request.end is not None
            and request.start > request.end
        ):
            raise _Invalid()
        if request.after is not None:
            preview_key(request.after, request)
        return {
            "version": WORKER_PROTOCOL_VERSION,
            "operation": "preview",
            "dataset": request.dataset.id,
            "files": files.add(request.files),
            "start_date": None if request.start is None else request.start.isoformat(),
            "end_date": None if request.end is None else request.end.isoformat(),
            "after": request.after,
            "page_size": request.size,
            "facility": request.facility,
        }

    def _query(self, request: QueryRead, files: _FileBudget) -> dict[str, object]:
        if (
            not isinstance(request.sql, str)
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
            relations.append({"dataset": dataset.id, "files": files.add(approved)})
        return {
            "version": WORKER_PROTOCOL_VERSION,
            "operation": "query",
            "sql": request.sql,
            "relations": relations,
        }
