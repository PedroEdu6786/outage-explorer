"""Local contributor connector seams, independent of storage and HTTP libraries."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from outage_explorer.application.dto import ConnectorReport, ResourceReport
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    ExactArtifactStore,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    ResourceBaseline,
    SanitizedPage,
    TransientInput,
    validate_resources,
)
from outage_explorer.application.ports.source import SourcePages, SourceRequest
from outage_explorer.domain.refresh import RefreshBounds


class ConnectorEvents(Protocol):
    """Best-effort diagnostics: fixed event names and safe counts/identities only."""

    def emit(self, event: str, **details: str | int) -> None: ...


class ConnectorSourceFactory(Protocol):
    def __call__(self, request: SourceRequest) -> SourcePages: ...


class ConnectorEvidence(Protocol):
    def write(self, pages: Iterable[SanitizedPage]) -> EvidenceBundle: ...

    def reopen(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> CandidateManifest: ...


class ConnectorReports(Protocol):
    def progress(self, report: ConnectorReport) -> None: ...

    def finish(self, report: ConnectorReport) -> None: ...


class ResourceInputs(Protocol):
    def collect_resources(self, pages: Iterable[SanitizedPage]) -> TransientInput: ...

    def verify_baseline(
        self, baseline: ResourceBaseline, bounds: RefreshBounds
    ) -> None: ...


class ResourceReports(Protocol):
    def progress(self, report: ResourceReport) -> None: ...

    def finish(self, report: ResourceReport) -> None: ...


@dataclass(frozen=True)
class DurableResourceReceipt:
    """All-file durable readback result; no manifest or publication authority."""

    generation_id: str
    resources: tuple[ArtifactRef, ...]

    def __post_init__(self) -> None:
        validate_resources(self.resources)
        if not self.generation_id:
            raise ArtifactError("Missing durable generation identity")


@dataclass(frozen=True)
class DurableConnectorReceipt:
    """Complete verified storage graph; confers no active publication."""

    manifest: StoredObject
    objects: int
    byte_count: int


class ConnectorGraph(Protocol):
    def graph(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> tuple[StoredObject, ...]: ...

    def read(self, reference: StoredObject) -> Iterator[bytes]: ...

    def restore(
        self, reference: StoredObject, source: ExactArtifactStore, bounds: RefreshBounds
    ) -> CandidateManifest: ...

    def verify_remote(
        self, reference: StoredObject, source: ExactArtifactStore, bounds: RefreshBounds
    ) -> None: ...
