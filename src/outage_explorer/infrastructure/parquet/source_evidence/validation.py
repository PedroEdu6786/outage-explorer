"""Validate sanitized source pages and transient transport audit shapes."""

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import Interval
from outage_explorer.infrastructure.parquet.schemas import origin_record
from outage_explorer.infrastructure.parquet.value_bounds import value_size

_AUDIT_FIELDS = {
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


def validate_json_types(value: object, bounds: ArtifactBounds, depth: int = 0) -> None:
    if depth > bounds.json_depth:
        raise ArtifactLimitError("Exceeded JSON depth")
    if type(value) in (str, int, float, bool, type(None)):
        value_size(value, bounds)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ArtifactError("JSON object keys must be strings")
            value_size(key, bounds)
            validate_json_types(item, bounds, depth + 1)
    elif type(value) is list:
        for item in value:
            validate_json_types(item, bounds, depth + 1)
    else:
        raise ArtifactError("Sanitized evidence must contain only JSON types")


def check_page(
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


def audit_descriptor(
    item: object, bounds: ArtifactBounds
) -> tuple[dict[str, object], int]:
    size = value_size(item, bounds)
    validate_json_types(item, bounds)
    if not isinstance(item, dict) or set(item) != _AUDIT_FIELDS:
        raise ArtifactError("Invalid transient transport descriptor")
    if (
        type(item["version"]) is not int
        or item["version"] != 1
        or type(item["offset"]) is not int
        or item["offset"] < 0
        or type(item["attempt"]) is not int
        or item["attempt"] <= 0
        or type(item["used"]) is not bool
    ):
        raise ArtifactError("Invalid transient transport descriptor")
    if (
        not isinstance(item["request_id"], str)
        or not isinstance(item["parameters"], dict)
        or not isinstance(item["envelope"], dict)
    ):
        raise ArtifactError("Invalid transient transport descriptor")
    response = item["envelope"].get("response")
    if not isinstance(response, dict) or not isinstance(response.get("data"), list):
        raise ArtifactError("Invalid transient transport envelope")
    return item, size
