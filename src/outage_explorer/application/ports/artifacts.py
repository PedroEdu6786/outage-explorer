"""Immutable artifact identities and explicit caller resource budgets."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from outage_explorer.domain.observations import Grain

ArtifactKind = Literal["raw", "pages", "dispositions", "modeled", "ledger"]


class ArtifactError(ValueError):
    """Artifact integrity or unsupported physical representation."""


class RepresentationError(ArtifactError):
    """Otherwise-valid input cannot be represented exactly; never an exclusion."""


class ArtifactLimitError(ArtifactError):
    """An explicit local resource budget was exhausted."""


@dataclass(frozen=True)
class ArtifactBounds:
    batch_rows: int
    row_group_rows: int
    row_group_bytes: int
    file_bytes: int
    total_bytes: int
    objects: int
    field_bytes: int
    json_depth: int

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Artifact bounds must be positive integers")


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    byte_count: int


@dataclass(frozen=True)
class ArtifactRef:
    object: StoredObject
    kind: ArtifactKind
    grain: Grain
    partition: date | None
    row_count: int
    schema_version: str = "1"


class ArtifactStore(Protocol):
    def put_immutable(self, chunks: Iterable[bytes]) -> StoredObject: ...

    def read(self, reference: StoredObject) -> Iterator[bytes]: ...

    def verify(self, reference: StoredObject) -> None: ...


@dataclass(frozen=True)
class TransferBounds:
    """Network transfer caps, including retries and verification reads."""

    attempts: int = 3
    elapsed_seconds: int = 1_800
    timeout_seconds: int = 10
    wire_bytes: int = 1_600_000_000
    chunk_bytes: int = 65536
    requests: int = 100_000
    temporary_bytes: int = 100_000_000

    def __post_init__(self) -> None:
        if any(type(value) is not int or value <= 0 for value in vars(self).values()):
            raise ValueError("Transfer bounds must be positive integers")


class ExactArtifactStore(Protocol):
    """Application-generated identities, scoped to configured storage only."""

    def put_exact(self, reference: StoredObject, chunks: Iterable[bytes]) -> None: ...

    def read(self, reference: StoredObject) -> Iterator[bytes]: ...
