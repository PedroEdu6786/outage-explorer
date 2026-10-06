"""Explicit v1 physical schemas and exact source/model codecs."""

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

import pyarrow as pa  # type: ignore[import-untyped]

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactKind,
    RepresentationError,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS, Dataset
from outage_explorer.domain.observations import Grain, SourceRecord, assess, calculate
from outage_explorer.domain.refresh import (
    IncomingRow,
    Interval,
    ModeledRow,
    Origin,
    RowDecision,
)


def _field(name: str, dtype: Any, nullable: bool = False) -> Any:
    return pa.field(name, dtype, nullable=nullable)


def _list(dtype: Any) -> Any:
    return pa.list_(pa.field("element", dtype, nullable=False))


def _origin_type() -> Any:
    return pa.struct(
        [
            *[
                _field(name, pa.string())
                for name in ("grain", "run_id", "retrieval_id", "request_id", "page_id")
            ],
            _field("retrieved_at", pa.timestamp("us", tz="UTC")),
            *[
                _field(name, pa.int64())
                for name in ("page_index", "row_index", "source_position")
            ],
            *[
                _field(name, pa.string())
                for name in ("contract_id", "transformation_id", "evidence_id")
            ],
        ]
    )


def _public_dataset(grain: Grain) -> Dataset:
    for dataset in PUBLIC_DATASETS:
        if dataset.grain == grain:
            return dataset
    raise ArtifactError("Unknown artifact grain")


def public_schema(grain: Grain) -> Any:
    """Public columns in declared order, typed exactly as the modeled schema."""
    modeled = schema_for("modeled", grain)
    return pa.schema(
        [modeled.field(column.name) for column in _public_dataset(grain).columns],
        metadata={b"kind": b"public", b"grain": grain.encode(), b"version": b"1"},
    )


def schema_for(kind: ArtifactKind, grain: Grain) -> Any:
    if grain not in ("national", "facility", "generator"):
        raise ArtifactError("Unknown artifact grain")
    if kind == "public":
        return public_schema(grain)
    origin = _field("origin", _origin_type())
    interval = [
        _field("interval_start", pa.date32()),
        _field("interval_end", pa.date32()),
    ]
    key = [_field("period", pa.date32()), _field("identity", _list(pa.string()))]
    if kind == "raw":
        fields = [origin, *interval, _field("value_json", pa.string())]
    elif kind == "pages":
        fields = [
            origin,
            *interval,
            *[
                _field(name, pa.int64())
                for name in ("offset", "length", "attempt", "returned_count")
            ],
            *[
                _field(name, pa.string())
                for name in (
                    "source_total",
                    "route",
                    "parameters_json",
                    "metadata_json",
                    "api_version",
                    "raw_refs_json",
                )
            ],
        ]
    elif kind == "dispositions":
        fields = [
            origin,
            _field("period", pa.date32(), True),
            _field("identity", _list(pa.string()), True),
            _field("status", pa.string()),
            _field("selected_position", pa.int64(), True),
            _field(
                "reasons",
                _list(
                    pa.struct(
                        [_field("field", pa.string()), _field("code", pa.string())]
                    )
                ),
            ),
        ]
    elif kind == "ledger":
        fields = [
            *key,
            _field("action", pa.string()),
            origin,
            _field("old_origin", _origin_type(), True),
            _field("exclusion_positions", _list(pa.int64())),
        ]
    elif kind == "modeled":
        fields = [
            *key,
            _field("facility_name", pa.string(), grain == "national"),
            *([_field("facility", pa.string())] if grain != "national" else []),
            *([_field("generator", pa.string())] if grain == "generator" else []),
            origin,
            *[
                _field(name, pa.string())
                for name in (
                    "capacity_source",
                    "outage_source",
                    "reported_percentage_source",
                    "capacity_units",
                    "outage_units",
                    "reported_percentage_units",
                    "share_numerator",
                    "share_denominator",
                    "percentage_numerator",
                    "percentage_denominator",
                    "calculated_percentage_display",
                    "reported_percentage_display",
                )
            ],
            *[
                _field(name, pa.decimal128(38, 12))
                for name in ("capacity_mw", "outage_mw", "reported_percentage")
            ],
            _field("calculated_percentage_rounded", pa.decimal128(38, 2)),
        ]
    else:
        raise ArtifactError("Unknown artifact kind")
    return pa.schema(
        fields,
        metadata={b"kind": kind.encode(), b"grain": grain.encode(), b"version": b"1"},
    )


def origin_record(origin: Origin) -> dict[str, object]:
    record = dict(vars(origin))
    if origin.grain not in ("national", "facility", "generator"):
        raise ArtifactError("Unknown origin grain")
    if (
        not isinstance(origin.retrieved_at, datetime)
        or origin.retrieved_at.utcoffset() is None
    ):
        raise ArtifactError("Origin timestamp must be timezone aware")
    for name in ("page_index", "row_index", "source_position"):
        value = record[name]
        if type(value) is not int or not 0 <= value < 2**63:
            raise ArtifactError("Invalid origin position")
    for name in (
        "run_id",
        "retrieval_id",
        "request_id",
        "page_id",
        "contract_id",
        "transformation_id",
        "evidence_id",
    ):
        if not isinstance(record[name], str) or not cast(str, record[name]).strip():
            raise ArtifactError("Empty origin identity")
    return record


def origin_from_record(record: dict[str, object]) -> Origin:
    try:
        origin = Origin(**cast(Any, record))
        origin_record(origin)
        return origin
    except (TypeError, KeyError, AttributeError) as exc:
        raise ArtifactError("Invalid origin record") from exc


def raw_record(row: IncomingRow, interval: Interval) -> dict[str, object]:
    return {
        "origin": origin_record(row.origin),
        "interval_start": interval.start,
        "interval_end": interval.end,
        "value_json": json.dumps(
            row.value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ),
    }


def raw_from_record(record: dict[str, object]) -> IncomingRow:
    try:
        return IncomingRow(
            origin_from_record(cast(dict[str, object], record["origin"])),
            json.loads(cast(str, record["value_json"])),
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise ArtifactError("Invalid raw record") from exc


def _decimal(value: Decimal, scale: int) -> Decimal:
    if not value.is_finite():
        raise RepresentationError("Nonfinite decimal")
    sign, digits, exponent = value.as_tuple()
    exp = cast(int, exponent)
    nonzero = any(digits)
    if nonzero:
        last = len(digits)
        while last and digits[last - 1] == 0:
            last -= 1
        if exp + len(digits) - last < -scale or len(digits) + exp > 38 - scale:
            raise RepresentationError("Decimal cannot fit exactly in physical schema")
    if not nonzero:
        return Decimal(0)
    # Exact tuple construction avoids Decimal context rounding and prevents
    # Fraction from expanding insignificant trailing source zeros.
    return Decimal((sign, digits[:last], exp + len(digits) - last))


def modeled_record(row: ModeledRow) -> dict[str, object]:
    observation, result = row.observation, row.result
    source = dict(observation.original)
    if len(source) != len(observation.original):
        raise ArtifactError("Duplicate source attributes")
    verified = assess(
        SourceRecord(row.origin.source_position, source), row.origin.grain
    ).observation
    if verified is not None:
        verified = replace(
            verified,
            capacity=_decimal(verified.capacity, 12),
            outage=_decimal(verified.outage, 12),
            reported_percentage=_decimal(verified.reported_percentage, 12),
        )
    if (
        verified is None
        or verified != observation
        or calculate(verified, row.origin.source_position) != result
    ):
        raise ArtifactError("Modeled value does not match original source")
    return {
        **(
            {"facility": observation.identity[0]}
            if row.origin.grain != "national"
            else {}
        ),
        **(
            {"generator": observation.identity[1]}
            if row.origin.grain == "generator"
            else {}
        ),
        "period": observation.day,
        "identity": list(observation.identity),
        "facility_name": observation.facility_name,
        "origin": origin_record(row.origin),
        "capacity_source": source["capacity"],
        "outage_source": source["outage"],
        "reported_percentage_source": source["percentOutage"],
        "capacity_units": source["capacity-units"],
        "outage_units": source["outage-units"],
        "reported_percentage_units": source["percentOutage-units"],
        "capacity_mw": _decimal(observation.capacity, 12),
        "outage_mw": _decimal(observation.outage, 12),
        "reported_percentage": _decimal(observation.reported_percentage, 12),
        "share_numerator": str(result.fraction.numerator),
        "share_denominator": str(result.fraction.denominator),
        "percentage_numerator": str(result.percentage.numerator),
        "percentage_denominator": str(result.percentage.denominator),
        "calculated_percentage_display": result.calculated_display,
        "reported_percentage_display": result.reported_display,
        "calculated_percentage_rounded": _decimal(
            Decimal(result.calculated_display), 2
        ),
    }


def public_record(record: dict[str, object]) -> dict[str, object]:
    """Project one modeled record to its public columns, without recomputation."""
    try:
        grain = cast(Grain, cast(dict[str, object], record["origin"])["grain"])
        return {
            column.name: record[column.name]
            for column in _public_dataset(grain).columns
        }
    except (KeyError, TypeError) as exc:
        raise ArtifactError("Invalid modeled record for public projection") from exc


def modeled_from_record(record: dict[str, object], grain: Grain) -> ModeledRow:
    try:
        origin = origin_from_record(cast(dict[str, object], record["origin"]))
        if origin.grain != grain:
            raise ArtifactError("Modeled grain mismatch")
        day = record["period"]
        if type(day) is not date:
            raise ArtifactError("Invalid modeled date")
        identity = cast(list[str], record["identity"])
        expected_length = {"national": 0, "facility": 1, "generator": 2}[grain]
        if len(identity) != expected_length:
            raise ArtifactError("Invalid modeled identity")
        source = {
            "period": day.isoformat(),
            "capacity": record["capacity_source"],
            "outage": record["outage_source"],
            "percentOutage": record["reported_percentage_source"],
            "capacity-units": record["capacity_units"],
            "outage-units": record["outage_units"],
            "percentOutage-units": record["reported_percentage_units"],
        }
        if grain != "national":
            source.update(facility=identity[0], facilityName=record["facility_name"])
        if grain == "generator":
            source["generator"] = identity[1]
        observation = assess(
            SourceRecord(origin.source_position, source), grain
        ).observation
        if observation is None:
            raise ArtifactError("Invalid modeled source")
        observation = replace(
            observation,
            capacity=_decimal(observation.capacity, 12),
            outage=_decimal(observation.outage, 12),
            reported_percentage=_decimal(observation.reported_percentage, 12),
        )
        row = ModeledRow(
            observation, origin, calculate(observation, origin.source_position)
        )
        if modeled_record(row) != record:
            raise ArtifactError(
                "Modeled physical fields disagree with source or calculation"
            )
        return row
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ArtifactError("Invalid modeled record") from exc


def disposition_record(decision: RowDecision) -> dict[str, object]:
    disposition = decision.disposition
    assessment = disposition.assessment
    return {
        "origin": origin_record(decision.origin),
        "period": assessment.day,
        "identity": list(assessment.identity)
        if assessment.identity is not None
        else None,
        "status": disposition.status,
        "selected_position": disposition.selected_position,
        "reasons": [
            {"field": reason.field, "code": reason.code}
            for reason in assessment.reasons
        ],
    }
