"""Capacity covers preparation, execution, termination and reaping."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.domain.datasets import Dataset


@dataclass(frozen=True)
class ExecutionBounds:
    preparation_seconds: int
    overall_seconds: int
    memory_bytes: int
    temporary_bytes: int
    output_bytes: int
    execution_seconds: int = 10

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Positive execution bounds required")
        if self.execution_seconds > 10:
            raise ValueError("Execution deadline cannot exceed ten seconds")


@dataclass(frozen=True)
class PreviewRead:
    dataset: Dataset
    files: tuple[ApprovedFile, ...]
    start: date | None
    end: date | None
    after: tuple[str, ...] | None
    size: int
    facility: str | None = None


@dataclass(frozen=True)
class PreviewRows:
    rows: tuple[tuple[object, ...], ...]
    keys: tuple[tuple[str, ...], ...]
    has_more: bool


@dataclass(frozen=True)
class QueryRead:
    sql: str
    relations: tuple[tuple[Dataset, tuple[ApprovedFile, ...]], ...]


class RecoveryLease(Protocol):
    """A strongly retained application lease, released only after safe reaping."""

    def close(self) -> None: ...


class ExecutionReservation(Protocol):
    def handoff(self, leases: tuple[RecoveryLease, ...]) -> None: ...
    def check_preparation(self) -> None: ...
    def preview(self, request: PreviewRead) -> PreviewRows: ...
    def query(self, request: QueryRead) -> QueryOutput: ...
    def close(self) -> None: ...


class IsolatedExecution(Protocol):
    def reserve(self) -> ExecutionReservation: ...
