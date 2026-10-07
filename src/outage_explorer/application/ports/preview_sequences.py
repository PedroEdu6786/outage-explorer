"""Ephemeral metadata only; sequence pins outlive individual page reads."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from outage_explorer.application.ports.analytical_inputs import PinnedInputs
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import ResourcePublishedGeneration


@dataclass(frozen=True)
class PreviewSequence:
    id: str
    user_id: str
    dataset: Dataset
    generation: ResourcePublishedGeneration
    start: date | None
    end: date | None
    size: int
    expires_at: datetime
    inputs: PinnedInputs
    facility: str | None = None


@dataclass(frozen=True)
class PreviewPosition:
    sequence: PreviewSequence
    after: tuple[str, ...] | None


class PreviewSequences(Protocol):
    def create(
        self,
        user_id: str,
        dataset: Dataset,
        generation: ResourcePublishedGeneration,
        start: date | None,
        end: date | None,
        size: int,
        inputs: PinnedInputs,
        *,
        facility: str | None = None,
    ) -> PreviewSequence: ...
    def cursor(
        self, sequence: PreviewSequence, after: tuple[str, ...] | None
    ) -> str: ...
    def acquire(
        self, cursor: str, user_id: str, dataset: Dataset
    ) -> PreviewPosition: ...
    def release(self, sequence: PreviewSequence) -> None: ...
    def discard(self, sequence: PreviewSequence) -> None: ...
    def cleanup(self) -> None: ...
