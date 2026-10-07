"""Replayable sanitized page evidence; transport sanitization lives upstream."""

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace
from typing import cast

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import SanitizedPage, TransientInput
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import IncomingRow, Interval
from outage_explorer.infrastructure.parquet.schemas import (
    origin_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore, value_size


def _json_types(value: object, store: LocalParquetStore, depth: int = 0) -> None:
    if depth > store.bounds.json_depth:
        raise ArtifactLimitError("Exceeded JSON depth")
    if type(value) in (str, int, float, bool, type(None)):
        value_size(value, store.bounds)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ArtifactError("JSON object keys must be strings")
            value_size(key, store.bounds)
            _json_types(item, store, depth + 1)
    elif type(value) is list:
        for item in value:
            _json_types(item, store, depth + 1)
    else:
        raise ArtifactError("Sanitized evidence must contain only JSON types")


def _check_page(
    page: SanitizedPage,
    interval: Interval,
    grain: Grain,
    page_index: int,
    position: int,
    retrieval: tuple[str, ...] | None,
    seen: set[tuple[str, str]],
) -> tuple[str, ...]:
    origin = page.origin
    origin_record(origin)
    identity = (
        origin.run_id,
        origin.retrieval_id,
        origin.contract_id,
        origin.transformation_id,
    )
    if (
        page.interval != interval
        or origin.grain != grain
        or (retrieval is not None and identity != retrieval)
    ):
        raise ArtifactError("Mixed page interval, grain or retrieval")
    if (
        origin.page_index != page_index
        or origin.row_index != 0
        or origin.source_position != position
    ):
        raise ArtifactError("Page/source ordering mismatch")
    if type(page.offset) is not int or page.offset != position:
        raise ArtifactError("Nonsequential page offset")
    if (
        type(page.length) is not int
        or not 0 < page.length < 2**63
        or len(page.values) > page.length
    ):
        raise ArtifactError("Invalid requested page length")
    if type(page.attempt) is not int or not 0 < page.attempt < 2**63:
        raise ArtifactError("Invalid accepted attempt")
    if (
        not isinstance(page.source_total, str)
        or not page.source_total.isascii()
        or not page.source_total.isdecimal()
    ):
        raise ArtifactError("Source total must be a nonnegative integer string")
    if not page.route or not page.api_version:
        raise ArtifactError("Missing route or API version")
    for kind, value in (
        ("page", origin.page_id),
        ("request", origin.request_id),
        ("evidence", origin.evidence_id),
    ):
        key = kind, value
        if key in seen:
            raise ArtifactError("Duplicate page/request/evidence identity")
        seen.add(key)
    return identity


def _audit(item: object, store: LocalParquetStore) -> dict[str, object]:
    value_size(item, store.bounds)
    _json_types(item, store)
    if (
        not isinstance(item, dict)
        or set(item)
        != {
            "version",
            "offset",
            "parameters",
            "request_id",
            "received_at",
            "attempt",
            "failures",
            "redacted_paths",
            "envelope",
            "used",
        }
        or type(item["version"]) is not int
        or item["version"] != 1
        or type(item["offset"]) is not int
        or item["offset"] < 0
        or type(item["attempt"]) is not int
        or item["attempt"] <= 0
        or type(item["used"]) is not bool
        or not isinstance(item["request_id"], str)
        or not isinstance(item["parameters"], dict)
        or not isinstance(item["envelope"], dict)
    ):
        raise ArtifactError("Invalid transient transport descriptor")
    response = item["envelope"].get("response")
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise ArtifactError("Invalid transient transport envelope")
    return item


def collect_resources(
    store: LocalParquetStore, pages: Iterable[SanitizedPage]
) -> TransientInput:
    """Validate each complete source walk, keeping only bounded copied input rows.

    Page/transport metadata is checked as it arrives and discarded; no source,
    page, disposition, ledger or manifest object is installed in the store.
    """
    first: SanitizedPage | None = None
    rows: list[IncomingRow] = []
    seen: set[tuple[str, str]] = set()
    retrieval: tuple[str, ...] | None = None
    audits: dict[str, dict[str, object]] = {}
    matched: set[str] = set()
    used_requests: set[str] = set()
    byte_count = page_count = 0
    terminal = False
    for index, page in enumerate(pages):
        store.check()
        if index >= store.bounds.objects:
            raise ArtifactLimitError("Exceeded transient page count")
        if terminal:
            raise ArtifactError("Page follows empty terminal page")
        first = first or page
        retrieval = _check_page(
            page, first.interval, first.origin.grain, index, len(rows), retrieval, seen
        )
        page_count += 1
        for value in (
            page.parameters,
            page.metadata,
            page.route,
            page.api_version,
            page.source_total,
        ):
            size = value_size(value, store.bounds)
            _json_types(value, store)
            store.account_transient(size)
            byte_count += size
        if page.transport:
            if len(page.transport) > 3 or set(audits) != matched:
                raise ArtifactError("Unmatched or oversized transient transport window")
            audits, matched = {}, set()
            for item in page.transport:
                audit = _audit(item, store)
                size = value_size(item, store.bounds)
                store.account_transient(size)
                byte_count += size
                request_id = cast(str, audit["request_id"])
                if audit["used"]:
                    if request_id in used_requests:
                        raise ArtifactError("Repeated transient used request")
                    used_requests.add(request_id)
                    audits[request_id] = audit
        if audits:
            canonical = audits.get(page.origin.request_id)
            if canonical is None:
                raise ArtifactError("Missing transient canonical request")
            response = cast(
                dict[str, object],
                cast(dict[str, object], canonical["envelope"])["response"],
            )
            if (
                canonical["offset"] != page.offset
                or canonical["parameters"] != page.parameters
                or canonical["attempt"] != page.attempt
                or canonical["received_at"] != page.origin.retrieved_at.isoformat()
                or response.get("total") != page.source_total
                or response["data"] != list(page.values)
            ):
                raise ArtifactError("Transient canonical transport mismatch")
            matched.add(page.origin.request_id)
        for row_index, value in enumerate(page.values):
            store.check()
            size = value_size(value, store.bounds) + value_size(
                vars(page.origin), store.bounds
            )
            _json_types(value, store)
            store.account_transient(size)
            byte_count += size
            if byte_count > store.bounds.total_bytes:
                raise ArtifactLimitError("Exceeded transient input bytes")
            rows.append(
                IncomingRow(
                    replace(
                        page.origin, row_index=row_index, source_position=len(rows)
                    ),
                    deepcopy(value),
                )
            )
        if byte_count > store.bounds.total_bytes:
            raise ArtifactLimitError("Exceeded transient input bytes")
        terminal = not page.values
    if first is None:
        raise ArtifactError("Input needs at least one accepted page")
    if not terminal:
        raise ArtifactError("Missing empty terminal source page")
    if set(audits) != matched:
        raise ArtifactError("Unmatched transient transport window")
    return TransientInput(
        first.origin.grain,
        first.interval,
        tuple(rows),
        page_count,
        byte_count,
        first.origin.run_id,
        first.origin.contract_id,
        first.origin.transformation_id,
    )
