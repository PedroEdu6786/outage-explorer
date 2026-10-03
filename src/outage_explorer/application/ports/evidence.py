from typing import Protocol

from outage_explorer.application.dto import (
    EvidenceBundle,
    ReportLocations,
    VerificationReport,
)


class RecordedEvidence(Protocol):
    def load(self, bundle_reference: str) -> EvidenceBundle: ...


class ReportWriter(Protocol):
    def write(
        self, report: VerificationReport, destination: str
    ) -> ReportLocations: ...
