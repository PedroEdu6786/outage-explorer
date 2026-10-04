"""Local contributor connector seams, independent of storage and HTTP libraries."""

from collections.abc import Iterable
from typing import Protocol

from outage_explorer.application.dto import ConnectorReport
from outage_explorer.application.ports.artifacts import StoredObject
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
    SanitizedPage,
)
from outage_explorer.application.ports.source import SourcePages, SourceRequest
from outage_explorer.domain.refresh import RefreshBounds


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
