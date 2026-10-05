"""Unavailable analytical ports require no fabricated budgets or runtime state."""

from datetime import date

from outage_explorer.application.errors import (
    PreviewUnavailableError,
    QueryUnavailableError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import PinnedInputs
from outage_explorer.application.ports.execution import ExecutionReservation
from outage_explorer.application.ports.preview_sequences import (
    PreviewPosition,
    PreviewSequence,
)
from outage_explorer.application.ports.query_results import (
    ResultReader,
    ResultReservation,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import PublishedGeneration


class UnavailableInputs:
    def prepare(
        self, generation: PublishedGeneration, dataset: Dataset
    ) -> PinnedInputs:
        raise RuntimeUnavailableError("Analytical resources unavailable")


class UnavailableExecution:
    def reserve(self) -> ExecutionReservation:
        raise RuntimeUnavailableError("Analytical resources unavailable")


class UnavailableResults:
    def reserve(self, owner: str) -> ResultReservation:
        raise RuntimeUnavailableError("Analytical resources unavailable")

    def acquire(self, identity: str, owner: str) -> ResultReader:
        raise QueryUnavailableError("Query unavailable")


class UnavailableSequences:
    def create(
        self,
        user_id: str,
        dataset: Dataset,
        generation: PublishedGeneration,
        start: date | None,
        end: date | None,
        size: int,
        inputs: PinnedInputs,
    ) -> PreviewSequence:
        raise RuntimeUnavailableError("Analytical resources unavailable")

    def cursor(self, sequence: PreviewSequence, after: tuple[str, ...] | None) -> str:
        raise RuntimeUnavailableError("Analytical resources unavailable")

    def acquire(self, cursor: str, user_id: str, dataset: Dataset) -> PreviewPosition:
        raise PreviewUnavailableError("Preview unavailable")

    def release(self, sequence: PreviewSequence) -> None:
        pass

    def discard(self, sequence: PreviewSequence) -> None:
        pass

    def cleanup(self) -> None:
        pass
