"""Bounded source retrieval contracts; no HTTP types or credentials in evidence."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import Interval

ROUTES: dict[Grain, str] = {
    "national": "us-nuclear-outages",
    "facility": "facility-nuclear-outages",
    "generator": "generator-nuclear-outages",
}
ORDERING_ID = "period-facility-magnitude-generator-text-ascending-recorded-order-v2"


class SourceError(ValueError):
    """Retrieval failure, never a row exclusion or publication permission."""


class SourceLimitError(SourceError):
    """Explicit caller budget exhausted; no production defaults are implied."""


@dataclass(frozen=True)
class SourceBounds:
    interval_days: int
    page_rows: int
    rows: int
    pages: int
    requests: int
    attempts: int
    request_bytes: int
    response_bytes: int
    total_bytes: int
    output_bytes: int
    json_depth: int
    json_nodes: int
    field_bytes: int
    elapsed_seconds: int
    timeout_seconds: int
    backoff_seconds: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise SourceError("Source bounds must be positive integers")
        if self.page_rows > 5000:
            raise SourceError("EIA JSON page length cannot exceed 5000")


@dataclass(frozen=True)
class SourceRequest:
    grain: Grain
    interval: Interval
    run_id: str
    retrieval_id: str
    contract_id: str
    transformation_id: str
    frequency: str = "daily"
    ordering_id: str = ORDERING_ID

    def __post_init__(self) -> None:
        if self.grain not in ROUTES:
            raise SourceError("Unsupported EIA route")
        if self.frequency != "daily" or self.ordering_id != ORDERING_ID:
            raise SourceError("Unsupported frequency or ordering contract")
        if any(
            not value
            for value in (
                self.run_id,
                self.retrieval_id,
                self.contract_id,
                self.transformation_id,
            )
        ):
            raise SourceError("Missing source request identity")

    @property
    def route(self) -> str:
        return ROUTES[self.grain]

    @property
    def sort_columns(self) -> tuple[str, ...]:
        return {
            "national": ("period",),
            "facility": ("period", "facility"),
            "generator": ("period", "facility", "generator"),
        }[self.grain]


@dataclass(frozen=True)
class PageRequest:
    offset: int
    page_index: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value < 0 for value in vars(self).values()):
            raise SourceError("Invalid page position")


@dataclass(frozen=True)
class SourceMetadata:
    request_id: str
    retrieved_at: datetime
    attempt: int
    envelope: object
    redacted_paths: tuple[str, ...]


@dataclass(frozen=True)
class SourceQuality:
    grain: Grain
    requested: Interval
    received: int
    advertised_totals: tuple[str, ...]
    totals_changed: bool
    count_mismatch: bool
    observed_dates: tuple[date, ...]
    observed_entities: tuple[tuple[str, ...], ...]
    diagnostics: tuple[str, ...]
    # Only modeling can determine usability; observed roster is not completeness.
    upstream_completeness: str = "unverified"


class SourcePages(Protocol):
    """One sequential retrieval; a summary exists only after an empty terminator."""

    @property
    def quality(self) -> SourceQuality | None: ...

    def fetch_metadata(self) -> SourceMetadata: ...

    def fetch_page(self, request: PageRequest) -> SanitizedPage: ...

    def pages(self) -> Iterator[SanitizedPage]: ...
