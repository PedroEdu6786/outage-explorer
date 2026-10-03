"""Daily EIA observation contracts; pure validation, selection and arithmetic."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Literal

Grain = Literal["national", "facility", "generator"]
IDENTITY_FIELDS: dict[Grain, tuple[str, ...]] = {
    "national": (),
    "facility": ("facility",),
    "generator": ("facility", "generator"),
}


UNITS = {
    "capacity-units": "megawatts",
    "outage-units": "megawatts",
    "percentOutage-units": "percent",
}
NUMBERS = ("capacity", "outage", "percentOutage")
FIELDS = ("period", *NUMBERS, *UNITS)
NUMBER_PATTERN = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"


def fields_for(grain: Grain) -> tuple[str, ...]:
    return (
        FIELDS
        + IDENTITY_FIELDS[grain]
        + (() if grain == "national" else ("facilityName",))
    )


@dataclass(frozen=True)
class SourceRecord:
    position: int
    value: object


@dataclass(frozen=True)
class Reason:
    code: str
    field: str


@dataclass(frozen=True)
class Observation:
    day: date
    capacity: Decimal
    outage: Decimal
    reported_percentage: Decimal
    original: tuple[tuple[str, str], ...] = field(compare=False)
    identity: tuple[str, ...] = ()
    facility_name: str | None = None


@dataclass(frozen=True)
class Assessment:
    position: int
    day: date | None
    observation: Observation | None
    reasons: tuple[Reason, ...]
    identity: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Disposition:
    assessment: Assessment
    status: Literal["selected", "excluded", "duplicate", "superseded"]
    selected_position: int | None


def parse_day(value: str) -> date | None:
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def assess(record: SourceRecord, grain: Grain = "national") -> Assessment:
    """Collect all invalid fields without counting a row multiple times."""
    if not isinstance(record.value, Mapping):
        return Assessment(record.position, None, None, (Reason("not_object", "$"),))
    raw = record.value
    fields = fields_for(grain)
    reasons = [
        Reason("unexpected_attribute", str(key)) for key in raw if key not in fields
    ]
    strings: dict[str, str] = {}
    for name in fields:
        value = raw.get(name)
        if name not in raw:
            reasons.append(Reason("missing", name))
        elif not isinstance(value, str):
            reasons.append(Reason("not_string", name))
        elif not value.strip():
            reasons.append(Reason("empty", name))
        else:
            strings[name] = value
    identity_fields = IDENTITY_FIELDS[grain]
    for name in identity_fields:
        if name in strings and strings[name] != strings[name].strip():
            reasons.append(Reason("invalid_identifier", name))
    identity = (
        tuple(strings[name] for name in identity_fields)
        if all(
            name in strings and strings[name] == strings[name].strip()
            for name in identity_fields
        )
        else None
    )
    day = parse_day(strings["period"]) if "period" in strings else None
    if "period" in strings and day is None:
        reasons.append(Reason("invalid_date", "period"))
    numbers: dict[str, Decimal] = {}
    for name in NUMBERS:
        if name in strings:
            try:
                if not re.fullmatch(NUMBER_PATTERN, strings[name]):
                    raise InvalidOperation
                number = Decimal(strings[name])
                if not number.is_finite():
                    raise InvalidOperation
                numbers[name] = number
            except InvalidOperation:
                reasons.append(Reason("invalid_number", name))
    for name, expected in UNITS.items():
        if name in strings and strings[name] != expected:
            reasons.append(Reason("incompatible_unit", name))
    if "capacity" in numbers and numbers["capacity"] <= 0:
        reasons.append(Reason("nonpositive_capacity", "capacity"))
    observation = None
    if not reasons and day is not None:
        observation = Observation(
            day,
            numbers["capacity"],
            numbers["outage"],
            numbers["percentOutage"],
            tuple((name, strings[name]) for name in fields),
            identity or (),
            strings.get("facilityName"),
        )
    return Assessment(
        record.position,
        day,
        observation,
        tuple(sorted(reasons, key=lambda r: (r.field, r.code))),
        identity,
    )


def select_daily(assessments: Sequence[Assessment]) -> tuple[Disposition, ...]:
    """Source position, never processing order, determines the last usable row."""
    if len({item.position for item in assessments}) != len(assessments):
        raise ValueError("Source positions must be unique")
    ordered = sorted(assessments, key=lambda item: item.position)
    winners = {
        (item.day, item.identity): item
        for item in ordered
        if item.observation is not None
    }
    dispositions = []
    for item in ordered:
        if item.observation is None:
            dispositions.append(Disposition(item, "excluded", None))
            continue
        winner = winners[(item.day, item.identity)]
        status: Literal["selected", "duplicate", "superseded"] = "superseded"
        if winner.position == item.position:
            status = "selected"
        elif winner.observation == item.observation:
            status = "duplicate"
        dispositions.append(Disposition(item, status, winner.position))
    return tuple(dispositions)


def present_percentage(value: Fraction) -> str:
    """Exact decimal half-up (ties away from zero), without context precision."""
    scaled = abs(value) * 100
    cents, remainder = divmod(scaled.numerator, scaled.denominator)
    if 2 * remainder >= scaled.denominator:
        cents += 1
    sign = "-" if value < 0 and cents else ""
    return f"{sign}{cents // 100}.{cents % 100:02d}"


@dataclass(frozen=True)
class DailyResult:
    observation: Observation
    source_position: int
    fraction: Fraction
    percentage: Fraction
    calculated_display: str
    reported_display: str


def calculate(observation: Observation, position: int) -> DailyResult:
    share = Fraction(observation.outage) / Fraction(observation.capacity)
    percentage = share * 100
    return DailyResult(
        observation,
        position,
        share,
        percentage,
        present_percentage(percentage),
        present_percentage(Fraction(observation.reported_percentage)),
    )
