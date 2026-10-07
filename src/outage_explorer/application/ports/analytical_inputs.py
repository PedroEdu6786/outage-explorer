"""Only verified, public modeled projections cross the analytical boundary."""

from dataclasses import dataclass
from typing import Protocol

from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import (
    ResourcePublishedGeneration,
)


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


class PublishedResourceInputs(Protocol):
    """Exact-descriptor inputs, prepared before the shared composition switch."""

    def prepare(
        self, generation: ResourcePublishedGeneration, dataset: Dataset
    ) -> PinnedInputs: ...
