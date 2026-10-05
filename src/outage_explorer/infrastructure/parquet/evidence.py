"""Replayable sanitized page evidence; transport sanitization lives upstream."""

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict, replace
from datetime import date
from typing import cast

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import EvidenceBundle, SanitizedPage
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import IncomingRow, Interval
from outage_explorer.infrastructure.parquet.schemas import (
    origin_from_record,
    origin_record,
    raw_from_record,
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


def _json(value: object, store: LocalParquetStore) -> str:
    value_size(value, store.bounds)
    _json_types(value, store)
    chunks = []
    size = 0
    try:
        for chunk in json.JSONEncoder(
            ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > store.bounds.field_bytes:
                raise ArtifactLimitError("Exceeded encoded JSON field bytes")
            chunks.append(chunk)
    except ArtifactError:
        raise
    except (ValueError, OverflowError, UnicodeError) as exc:
        raise ArtifactError("Invalid JSON evidence") from exc
    return "".join(chunks)


def _loads(value: object, store: LocalParquetStore) -> object:
    if not isinstance(value, str):
        raise ArtifactError("Expected encoded JSON string")
    try:
        result: object = json.loads(value)
        _json(result, store)
        return result
    except ArtifactError:
        raise
    except (ValueError, RecursionError) as exc:
        raise ArtifactError("Invalid stored JSON") from exc


def _refs_json(refs: tuple[ArtifactRef, ...], store: LocalParquetStore) -> str:
    return _json([asdict(ref) for ref in refs], store)


def _refs(value: object, store: LocalParquetStore) -> tuple[ArtifactRef, ...]:
    decoded = _loads(value, store)
    if not isinstance(decoded, list) or len(decoded) > store.bounds.objects:
        raise ArtifactError("Invalid page raw references")
    result = []
    try:
        for ref in decoded:
            if not isinstance(ref, dict) or set(ref) != {
                "object",
                "kind",
                "grain",
                "partition",
                "row_count",
                "schema_version",
            }:
                raise ArtifactError("Malformed page raw reference")
            if ref["partition"] is not None or ref["kind"] != "raw":
                raise ArtifactError("Page must reference unpartitioned raw evidence")
            result.append(
                ArtifactRef(
                    StoredObject(**ref["object"]),
                    ref["kind"],
                    ref["grain"],
                    None,
                    ref["row_count"],
                    ref["schema_version"],
                )
            )
    except (TypeError, KeyError) as exc:
        raise ArtifactError("Malformed raw reference") from exc
    return tuple(result)


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


def _page_rows(
    store: LocalParquetStore, page: SanitizedPage, position: int
) -> Iterator[dict[str, object]]:
    for row_index, value in enumerate(page.values):
        origin = replace(
            page.origin, row_index=row_index, source_position=position + row_index
        )
        yield {
            "origin": origin_record(origin),
            "interval_start": page.interval.start,
            "interval_end": page.interval.end,
            "value_json": _json(value, store),
        }


def write_evidence(
    store: LocalParquetStore, pages: Iterable[SanitizedPage]
) -> EvidenceBundle:
    raw_refs: list[ArtifactRef] = []
    page_refs: list[ArtifactRef] = []
    transport_refs: list[StoredObject] = []
    interval: Interval | None = None
    grain: Grain | None = None
    position = 0
    retrieval: tuple[str, ...] | None = None
    seen: set[tuple[str, str]] = set()
    terminal = False
    for page_index, page in enumerate(pages):
        if page_index >= store.bounds.objects:
            raise ArtifactLimitError("Exceeded page count")
        if terminal:
            raise ArtifactError("Page follows empty terminal page")
        interval = interval or page.interval
        grain = grain or page.origin.grain
        retrieval = _check_page(
            page, interval, grain, page_index, position, retrieval, seen
        )
        parameters = _json(page.parameters, store)
        metadata_value = page.metadata
        if page.transport:
            if (
                not isinstance(metadata_value, dict)
                or "transport_refs" in metadata_value
            ):
                raise ArtifactError("Invalid supplemental transport metadata")
            window_refs = []
            for item in page.transport:
                _json_types(item, store)
                payload = json.dumps(
                    item,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
                ref = store.put_immutable((payload,))
                window_refs.append(ref)
                transport_refs.append(ref)
            metadata_value = metadata_value | {
                "transport_refs": [asdict(ref) for ref in window_refs],
                "transport_counts": {
                    "requests": len(page.transport),
                    "fetched_rows": sum(
                        len(
                            cast(
                                dict[str, dict[str, list[object]]],
                                cast(dict[str, object], item)["envelope"],
                            )["response"]["data"]
                        )
                        for item in page.transport
                    ),
                    "unused_responses": sum(
                        not cast(dict[str, object], item)["used"]
                        for item in page.transport
                    ),
                },
            }
        metadata = _json(metadata_value, store)

        refs = store.write("raw", grain, None, _page_rows(store, page, position))
        raw_refs.extend(refs)
        record = {
            "origin": origin_record(page.origin),
            "interval_start": interval.start,
            "interval_end": interval.end,
            "offset": page.offset,
            "length": page.length,
            "attempt": page.attempt,
            "returned_count": len(page.values),
            "source_total": page.source_total,
            "route": page.route,
            "parameters_json": parameters,
            "metadata_json": metadata,
            "api_version": page.api_version,
            "raw_refs_json": _refs_json(refs, store),
        }
        page_refs.extend(store.write("pages", grain, None, [record]))
        position += len(page.values)
        terminal = not page.values
    if interval is None or grain is None:
        raise ArtifactError("Evidence needs at least one accepted page")
    bundle = EvidenceBundle(
        grain, interval, tuple(raw_refs), tuple(page_refs), tuple(transport_refs)
    )
    verify_evidence(store, bundle)
    return bundle


def _transport_audits(
    store: LocalParquetStore, references: tuple[StoredObject, ...]
) -> tuple[dict[str, dict[str, object]], dict[str, int]]:
    audits: dict[str, dict[str, object]] = {}
    fetched_rows = unused_responses = 0
    for transport_ref in references:
        payload = b"".join(store.read(transport_ref))
        try:
            item = json.loads(payload)
            _json_types(item, store)
        except (ValueError, UnicodeError, RecursionError):
            raise ArtifactError("Invalid supplemental transport JSON") from None
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
            or item["version"] != 1
            or type(item["version"]) is not int
            or type(item["offset"]) is not int
            or item["offset"] < 0
            or type(item["attempt"]) is not int
            or item["attempt"] <= 0
            or type(item["used"]) is not bool
            or not isinstance(item["request_id"], str)
            or not isinstance(item["envelope"], dict)
            or not isinstance(item["parameters"], dict)
        ):
            raise ArtifactError("Invalid supplemental transport descriptor")
        response = item["envelope"].get("response")
        if not isinstance(response, dict) or not isinstance(response.get("data"), list):
            raise ArtifactError("Invalid supplemental transport envelope")
        fetched_rows += len(response["data"])
        unused_responses += not item["used"]
        if item["used"]:
            if item["request_id"] in audits:
                raise ArtifactError("Repeated supplemental used request")
            audits[item["request_id"]] = item
    return audits, {
        "requests": len(references),
        "fetched_rows": fetched_rows,
        "unused_responses": unused_responses,
    }


def _scan_evidence(
    store: LocalParquetStore, bundle: EvidenceBundle
) -> Iterator[IncomingRow]:
    if (
        not bundle.pages
        or len(bundle.pages) + len(bundle.raw) + len(bundle.transport)
        > store.bounds.objects
    ):
        raise ArtifactError("Invalid evidence object count")
    if len({ref.object.key for ref in (*bundle.pages, *bundle.raw)}) != len(
        bundle.pages
    ) + len(bundle.raw):
        raise ArtifactError("Repeated evidence object")
    if (
        sum(ref.object.byte_count for ref in (*bundle.pages, *bundle.raw))
        + sum(ref.byte_count for ref in bundle.transport)
        > store.bounds.total_bytes
    ):
        raise ArtifactLimitError("Evidence exceeds total bytes")
    audits: dict[str, dict[str, object]] = {}
    referenced_transport: list[StoredObject] = []
    matched_audits: set[str] = set()
    position = page_index = raw_index = 0
    retrieval: tuple[str, ...] | None = None
    seen: set[tuple[str, str]] = set()
    terminal = False
    for page_ref in bundle.pages:
        if (
            page_ref.kind != "pages"
            or page_ref.grain != bundle.grain
            or page_ref.partition is not None
        ):
            raise ArtifactError("Page artifact metadata mismatch")
        for record in store.records(page_ref):
            if terminal:
                raise ArtifactError("Page follows empty terminal page")
            origin = origin_from_record(cast(dict[str, object], record["origin"]))
            interval = Interval(
                cast(date, record["interval_start"]), cast(date, record["interval_end"])
            )
            refs = _refs(record["raw_refs_json"], store)
            count = cast(int, record["returned_count"])
            if (
                type(count) is not int
                or count < 0
                or count != sum(ref.row_count for ref in refs)
            ):
                raise ArtifactError("Page returned count mismatch")
            # Avoid allocating placeholder rows for attacker-controlled returned_count.
            page = SanitizedPage(
                origin,
                interval,
                cast(int, record["offset"]),
                cast(int, record["length"]),
                cast(int, record["attempt"]),
                cast(str, record["source_total"]),
                cast(str, record["route"]),
                _loads(record["parameters_json"], store),
                _loads(record["metadata_json"], store),
                cast(str, record["api_version"]),
                (),
            )
            retrieval = _check_page(
                page,
                bundle.interval,
                bundle.grain,
                page_index,
                position,
                retrieval,
                seen,
            )
            if isinstance(page.metadata, dict) and "transport_refs" in page.metadata:
                try:
                    refs_value = page.metadata["transport_refs"]
                    if not isinstance(refs_value, list):
                        raise TypeError
                    if not 1 <= len(refs_value) <= 3:
                        raise ArtifactError("Invalid supplemental window width")
                    if matched_audits != set(audits):
                        raise ArtifactError("Unmatched supplemental window")
                    window_refs = tuple(StoredObject(**value) for value in refs_value)
                    referenced_transport.extend(window_refs)
                    audits, counts = _transport_audits(store, window_refs)
                    if page.metadata.get("transport_counts") != counts:
                        raise ArtifactError("Supplemental transport counts mismatch")
                    matched_audits = set()
                except (TypeError, ValueError):
                    raise ArtifactError(
                        "Invalid supplemental evidence reference"
                    ) from None
            audit = audits.get(origin.request_id)
            if bundle.transport:
                if (
                    audit is None
                    or audit["offset"] != page.offset
                    or audit["parameters"] != page.parameters
                    or audit["attempt"] != page.attempt
                    or audit["received_at"] != origin.retrieved_at.isoformat()
                ):
                    raise ArtifactError("Supplemental canonical request mismatch")
                audit_envelope = cast(dict[str, object], audit["envelope"])
                audit_response = cast(dict[str, object], audit_envelope["response"])
                audit_values = cast(list[object], audit_response["data"])
                if (
                    len(audit_values) != count
                    or audit_response["total"] != page.source_total
                ):
                    raise ArtifactError("Supplemental canonical count mismatch")
                matched_audits.add(origin.request_id)
            if count > page.length:
                raise ArtifactError("Page returned more than requested")
            row_index = 0
            for ref in refs:
                if (
                    raw_index >= len(bundle.raw)
                    or bundle.raw[raw_index] != ref
                    or ref.grain != bundle.grain
                ):
                    raise ArtifactError("Page/raw manifest linkage mismatch")
                raw_index += 1
                for raw in store.records(ref):
                    if (
                        raw["interval_start"] != interval.start
                        or raw["interval_end"] != interval.end
                    ):
                        raise ArtifactError("Raw interval mismatch")
                    expected = replace(
                        origin,
                        row_index=row_index,
                        source_position=position + row_index,
                    )
                    item = raw_from_record(raw)
                    _json(item.value, store)
                    if bundle.transport and item.value != audit_values[row_index]:
                        raise ArtifactError("Supplemental canonical raw value mismatch")
                    if item.origin != expected:
                        raise ArtifactError("Raw page origin mismatch")
                    yield item
                    row_index += 1
            if row_index != count:
                raise ArtifactError("Page raw count mismatch")
            position += count
            page_index += 1
            terminal = count == 0
    if tuple(referenced_transport) != bundle.transport or matched_audits != set(audits):
        raise ArtifactError("Unlinked supplemental transport evidence")
    if raw_index != len(bundle.raw):
        raise ArtifactError("Unlinked raw evidence")


def verify_evidence(store: LocalParquetStore, bundle: EvidenceBundle) -> None:
    for _ in _scan_evidence(store, bundle):
        pass


def replay_evidence(
    store: LocalParquetStore, bundle: EvidenceBundle
) -> Iterator[IncomingRow]:
    verify_evidence(store, bundle)
    yield from _scan_evidence(store, bundle)
