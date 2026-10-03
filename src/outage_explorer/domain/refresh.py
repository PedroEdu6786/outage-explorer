"""Bounded, pure refresh partitions; no retrieval, storage or publication.

Callers supply sanitized input and opaque evidence identifiers, not URLs or secrets.
These helpers neither sanitize evidence nor implement a whole-history merge. Each
call must contain a complete bounded group for its keys (including page overlaps).
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from outage_explorer.domain.observations import (
    IDENTITY_FIELDS,
    NUMBER_PATTERN,
    NUMBERS,
    DailyResult,
    Disposition,
    Grain,
    Observation,
    Reason,
    SourceRecord,
    assess,
    calculate,
    select_daily,
)

Key = tuple[date, tuple[str, ...]]


class RefreshInputError(ValueError):
    """Input integrity failure, never an ordinary row exclusion."""


class RefreshLimitError(RefreshInputError):
    """Configured resource budget exhausted; fail the candidate."""


class EmptySourceError(RefreshInputError):
    """A required route received no observations."""


@dataclass(frozen=True)
class Interval:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise RefreshInputError("Interval end precedes start")

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class RefreshBounds:
    """Explicit caller budgets, not measured production defaults."""

    incoming_rows: int
    prior_rows: int
    output_rows: int
    fields_per_row: int
    field_chars: int
    coefficient_digits: int
    absolute_exponent: int
    source_index: int
    interval_days: int
    reason_occurrences: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise RefreshInputError("Refresh bounds must be positive integers")


@dataclass(frozen=True)
class Origin:
    grain: Grain
    run_id: str
    retrieval_id: str
    request_id: str
    page_id: str
    retrieved_at: datetime
    page_index: int
    row_index: int
    source_position: int
    contract_id: str
    transformation_id: str
    evidence_id: str


@dataclass(frozen=True)
class IncomingRow:
    origin: Origin
    value: object


@dataclass(frozen=True)
class ModeledRow:
    observation: Observation
    origin: Origin
    result: DailyResult

    @property
    def key(self) -> Key:
        return self.observation.day, self.observation.identity


@dataclass(frozen=True)
class RowDecision:
    origin: Origin
    disposition: Disposition


@dataclass(frozen=True)
class Quality:
    received: int
    selected: int
    excluded: int
    duplicate: int
    superseded: int
    reason_counts: tuple[tuple[Reason, int], ...]


@dataclass(frozen=True)
class ModeledPartition:
    grain: Grain
    interval: Interval
    rows: tuple[ModeledRow, ...]
    decisions: tuple[RowDecision, ...]
    excluded_keys: frozenset[Key]
    observed_identities: frozenset[tuple[str, ...]]
    observed_dates: frozenset[date]
    quality: Quality

    @property
    def usable_keys(self) -> frozenset[Key]:
        return frozenset(row.key for row in self.rows)


@dataclass(frozen=True)
class MergedPartition:
    incoming: ModeledPartition
    rows: tuple[ModeledRow, ...]
    retained_invalid_keys: frozenset[Key]
    carried_outside_keys: frozenset[Key]
    absent_prior_rows: tuple[ModeledRow, ...]
    active_count: int

    @property
    def candidate_count(self) -> int:
        return len(self.rows)

    @property
    def retained_absent_keys(self) -> frozenset[Key]:
        return frozenset(row.key for row in self.absent_prior_rows)


@dataclass(frozen=True)
class RefreshFacts:
    mode: Literal["initial", "refresh"]
    all_excluded: bool
    all_excluded_grains: tuple[Grain, ...]
    absent_prior_keys: tuple[tuple[Grain, tuple[Key, ...]], ...]

    @property
    def retain_active_without_publication(self) -> bool:
        """Only an existing complete generation can be retained."""
        return self.mode == "refresh" and self.all_excluded

    @property
    def transformation_eligible(self) -> bool:
        """Pure row eligibility only; retrieval/storage/publication checks still apply."""
        if self.mode == "initial":
            return not self.all_excluded_grains
        return not self.all_excluded


def _limit(value: int, maximum: int, name: str) -> None:
    if value > maximum:
        raise RefreshLimitError(f"Exceeded {name} bound")


def _check_interval(interval: Interval, bounds: RefreshBounds) -> None:
    _limit((interval.end - interval.start).days + 1, bounds.interval_days, "interval")


def _check_origin(origin: Origin, grain: Grain, bounds: RefreshBounds) -> None:
    if origin.grain != grain:
        raise RefreshInputError("Origin grain mismatch")
    for name in ("page_index", "row_index", "source_position"):
        value = getattr(origin, name)
        if type(value) is not int or value < 0:
            raise RefreshInputError("Source indices must be nonnegative integers")
        _limit(value, bounds.source_index, "source index")
    for name in (
        "run_id",
        "retrieval_id",
        "request_id",
        "page_id",
        "contract_id",
        "transformation_id",
        "evidence_id",
    ):
        value = getattr(origin, name)
        if not isinstance(value, str) or not value.strip():
            raise RefreshInputError("Origin identifiers must be nonempty strings")
        _limit(len(value), bounds.field_chars, "origin identifier")
    if origin.retrieved_at.utcoffset() is None:
        raise RefreshInputError("Retrieval time must be timezone aware")


def _check_numeric(value: str, bounds: RefreshBounds) -> None:
    if not re.fullmatch(NUMBER_PATTERN, value):
        return  # Ordinary contract exclusion, not arithmetic expansion.
    coefficient, _, exponent = value.lower().partition("e")
    digits = sum(char.isdigit() for char in coefficient)
    _limit(digits, bounds.coefficient_digits, "coefficient digits")
    # Compare text before conversion, including exponents beyond Python's int cap.
    magnitude = exponent.lstrip("+-").lstrip("0") or "0"
    cap = str(bounds.absolute_exponent)
    if len(magnitude) > len(cap) or (len(magnitude) == len(cap) and magnitude > cap):
        raise RefreshLimitError("Exceeded absolute exponent bound")
    # Fraction(Decimal) also expands fractional places without an explicit exponent.
    fractional = len(coefficient.partition(".")[2])
    _limit(
        abs(
            (-int(magnitude) if exponent.startswith("-") else int(magnitude))
            - fractional
        ),
        bounds.absolute_exponent,
        "effective exponent",
    )


def _check_raw(value: object, bounds: RefreshBounds) -> None:
    if isinstance(value, str):
        _limit(len(value), bounds.field_chars, "field characters")
    if not isinstance(value, Mapping):
        return
    _limit(len(value), bounds.fields_per_row, "fields per row")
    for name, field in value.items():
        if not isinstance(name, str):
            raise RefreshInputError("Source object keys must be strings")
        _limit(len(name), bounds.field_chars, "field characters")
        if isinstance(field, str):
            _limit(len(field), bounds.field_chars, "field characters")
            if name in NUMBERS:
                _check_numeric(field, bounds)


def model_partition(
    grain: Grain,
    interval: Interval,
    incoming: Iterable[IncomingRow],
    bounds: RefreshBounds,
) -> ModeledPartition:
    """Model a complete bounded route group in authoritative source-position order.

    Empty input here means an empty route. Later streaming orchestration must
    handle absent date partitions separately within a nonempty route.
    """
    if grain not in IDENTITY_FIELDS:
        raise RefreshInputError("Unknown grain")
    _check_interval(interval, bounds)
    origins: dict[int, Origin] = {}
    assessments = []
    page_rows: set[tuple[int, int]] = set()
    retrieval: tuple[str, str, str, str] | None = None
    reasons: Counter[Reason] = Counter()
    reason_total = 0
    for count, item in enumerate(incoming, 1):
        _limit(count, bounds.incoming_rows, "incoming rows")
        _check_origin(item.origin, grain, bounds)
        origin = item.origin
        identity = (
            origin.run_id,
            origin.retrieval_id,
            origin.contract_id,
            origin.transformation_id,
        )
        if retrieval is not None and identity != retrieval:
            raise RefreshInputError("Mixed retrieval or transformation identities")
        retrieval = identity
        location = (origin.page_index, origin.row_index)
        if origin.source_position in origins or location in page_rows:
            raise RefreshInputError("Duplicate source position or page row")
        origins[origin.source_position] = origin
        page_rows.add(location)
        _check_raw(item.value, bounds)
        assessment = assess(SourceRecord(origin.source_position, item.value), grain)
        if assessment.day is not None and not interval.contains(assessment.day):
            raise RefreshInputError("Source observation outside requested interval")
        reason_total += len(assessment.reasons)
        _limit(reason_total, bounds.reason_occurrences, "reason occurrences")
        reasons.update(assessment.reasons)
        assessments.append(assessment)
    if not assessments:
        raise EmptySourceError("Required route received no observations")
    dispositions = select_daily(assessments)
    rows: list[ModeledRow] = []
    for disposition in dispositions:
        observation = disposition.assessment.observation
        if disposition.status == "selected" and observation is not None:
            _limit(len(rows) + 1, bounds.output_rows, "output rows")
            origin = origins[disposition.assessment.position]
            rows.append(
                ModeledRow(
                    observation,
                    origin,
                    calculate(observation, origin.source_position),
                )
            )
    counts = Counter(item.status for item in dispositions)
    return ModeledPartition(
        grain,
        interval,
        tuple(sorted(rows, key=lambda row: row.key)),
        tuple(
            RowDecision(origins[item.assessment.position], item)
            for item in dispositions
        ),
        frozenset(
            (item.day, item.identity)
            for item in assessments
            if item.observation is None
            and item.day is not None
            and item.identity is not None
        ),
        frozenset(item.identity for item in assessments if item.identity is not None),
        frozenset(item.day for item in assessments if item.day is not None),
        Quality(
            len(assessments),
            counts["selected"],
            counts["excluded"],
            counts["duplicate"],
            counts["superseded"],
            tuple(
                sorted(reasons.items(), key=lambda pair: (pair[0].field, pair[0].code))
            ),
        ),
    )


def _check_prior(row: ModeledRow, grain: Grain, bounds: RefreshBounds) -> None:
    _check_origin(row.origin, grain, bounds)
    _limit(len(row.observation.original), bounds.fields_per_row, "fields per row")
    raw = dict(row.observation.original)
    if len(raw) != len(row.observation.original):
        raise RefreshInputError("Duplicate prior source attributes")
    _check_raw(raw, bounds)
    verified = assess(SourceRecord(row.origin.source_position, raw), grain).observation
    if verified is None or verified != row.observation:
        raise RefreshInputError("Prior row is not a valid observation")
    expected = calculate(verified, row.origin.source_position)
    if row.result != expected:
        raise RefreshInputError("Prior derived value does not match source")


def merge_partition(
    incoming: ModeledPartition,
    prior: Iterable[ModeledRow],
    bounds: RefreshBounds,
) -> MergedPartition:
    """Merge a bounded prior group, retaining absent rows with original provenance.

    The caller must pass a result of model_partition and eventually check keys
    across the complete artifact manifest. This local check cannot prove that.
    """
    _check_interval(incoming.interval, bounds)
    _limit(incoming.quality.received, bounds.incoming_rows, "incoming rows")
    rows = {row.key: row for row in incoming.rows}
    if len(rows) != len(incoming.rows):
        raise RefreshInputError("Duplicate incoming modeled keys")
    _limit(len(rows), bounds.output_rows, "output rows")
    seen: set[Key] = set()
    retained: set[Key] = set()
    outside: set[Key] = set()
    absent = []
    for count, row in enumerate(prior, 1):
        _limit(count, bounds.prior_rows, "prior rows")
        _check_prior(row, incoming.grain, bounds)
        if row.key in seen:
            raise RefreshInputError("Duplicate prior modeled keys")
        seen.add(row.key)
        if row.key in rows:
            continue
        if not incoming.interval.contains(row.observation.day):
            outside.add(row.key)
        elif row.key in incoming.excluded_keys:
            retained.add(row.key)
        else:
            absent.append(row)
        _limit(len(rows) + 1, bounds.output_rows, "output rows")
        rows[row.key] = row
    return MergedPartition(
        incoming,
        tuple(sorted(rows.values(), key=lambda row: row.key)),
        frozenset(retained),
        frozenset(outside),
        tuple(sorted(absent, key=lambda row: row.key)),
        len(seen),
    )


def refresh_facts(partitions: Iterable[MergedPartition]) -> RefreshFacts:
    """Evaluate exactly three bounded route groups, never publication rights.

    Prior counts must describe complete supplied routes. Later streaming callers
    must aggregate route counts before applying initial-load or refresh policy.
    """
    by_grain: dict[Grain, MergedPartition] = {}
    for count, partition in enumerate(partitions, 1):
        if count > len(IDENTITY_FIELDS) or partition.incoming.grain in by_grain:
            raise RefreshInputError("Expected exactly one partition per grain")
        by_grain[partition.incoming.grain] = partition
    if set(by_grain) != set(IDENTITY_FIELDS):
        raise RefreshInputError("All three grains are required")
    if len({part.incoming.interval for part in by_grain.values()}) != 1:
        raise RefreshInputError("Route intervals differ")
    populated = sum(part.active_count > 0 for part in by_grain.values())
    if populated not in (0, len(IDENTITY_FIELDS)):
        raise RefreshInputError("Prior generation must contain all three grains")
    mode: Literal["initial", "refresh"] = "refresh" if populated else "initial"
    excluded = []
    absent = []
    for grain in IDENTITY_FIELDS:
        partition = by_grain[grain]
        quality = partition.incoming.quality
        if quality.received == 0:
            raise EmptySourceError("Required route received no observations")
        if quality.received == quality.excluded:
            excluded.append(grain)
        if partition.absent_prior_rows:
            absent.append(
                (grain, tuple(row.key for row in partition.absent_prior_rows))
            )
    return RefreshFacts(
        mode, len(excluded) == len(IDENTITY_FIELDS), tuple(excluded), tuple(absent)
    )
