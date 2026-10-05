"""Versioned public projections. Storage/provenance columns are deliberately private."""

from dataclasses import dataclass

from outage_explorer.domain.observations import Grain


@dataclass(frozen=True)
class ValueType:
    kind: str
    precision: int | None = None
    scale: int | None = None
    children: tuple[tuple[str, "ValueType"], ...] = ()


@dataclass(frozen=True)
class Column:
    name: str
    value_type: ValueType
    nullable: bool | None = False
    unit: str | None = None


@dataclass(frozen=True)
class Dataset:
    id: str
    grain: Grain
    label: str
    columns: tuple[Column, ...]
    schema_version: str = "1"


_COMMON = (
    Column("period", ValueType("date")),
    Column("capacity_mw", ValueType("decimal", 38, 12), unit="MW"),
    Column("outage_mw", ValueType("decimal", 38, 12), unit="MW"),
    Column("reported_percentage", ValueType("decimal", 38, 12), unit="percent"),
)
_FACILITY = (
    Column("facility", ValueType("string")),
    Column("facility_name", ValueType("string")),
)
PUBLIC_DATASETS = (
    Dataset(
        "national",
        "national",
        "National",
        (
            *_COMMON,
            Column(
                "calculated_percentage_rounded",
                ValueType("decimal", 38, 2),
                unit="percent",
            ),
            Column("percentage_numerator", ValueType("string")),
            Column("percentage_denominator", ValueType("string")),
            Column(
                "calculated_percentage_display", ValueType("string"), unit="percent"
            ),
            Column("reported_percentage_display", ValueType("string"), unit="percent"),
        ),
    ),
    Dataset("facilities", "facility", "Facilities", (*_COMMON, *_FACILITY)),
    Dataset(
        "generators",
        "generator",
        "Generators",
        (*_COMMON, *_FACILITY, Column("generator", ValueType("string"))),
    ),
)
