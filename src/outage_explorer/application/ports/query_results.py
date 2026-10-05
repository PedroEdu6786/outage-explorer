"""Bounded ephemeral retention, in-flight reservations and short reader leases."""

from dataclasses import dataclass
from typing import Protocol

from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.query_results import ResultIdentity


@dataclass(frozen=True)
class QueryOutput:
    document: bytes
    retained_row_count: int
    truncation_reason: str | None


class ResultReservation(Protocol):
    def complete(
        self,
        output: QueryOutput,
        grains: frozenset[AnalyticalGrain],
        generation_id: str | None,
        page_size: int,
    ) -> ResultIdentity: ...
    def close(self) -> None: ...


class ResultReader(Protocol):
    @property
    def identity(self) -> ResultIdentity: ...
    def page(self, page: int) -> dict[str, object]: ...
    def close(self) -> None: ...


class QueryResults(Protocol):
    def reserve(self, owner: str) -> ResultReservation: ...
    def acquire(self, query_id: str, owner: str) -> ResultReader: ...
