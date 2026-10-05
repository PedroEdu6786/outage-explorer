"""Only verified, public modeled projections cross the analytical boundary."""

from dataclasses import dataclass
from typing import Protocol

from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import PublishedGeneration


@dataclass(frozen=True)
class ApprovedFile:
    path: str
    sha256: str
    byte_count: int
    rows: int


class PinnedInputs(Protocol):
    @property
    def files(self) -> tuple[ApprovedFile, ...]: ...
    def close(self) -> None: ...


class PublishedInputs(Protocol):
    def prepare(
        self, generation: PublishedGeneration, dataset: Dataset
    ) -> PinnedInputs: ...
