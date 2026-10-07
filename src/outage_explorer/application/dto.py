"""Transport-independent application results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

# Import only transport-independent contracts; no environment or filesystem types.
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorFailure,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
)
from outage_explorer.application.ports.source import SourceQuality
from outage_explorer.domain.access import SeededUser
from outage_explorer.domain.observations import (
    DailyResult,
    Disposition,
    Grain,
    SourceRecord,
)
from outage_explorer.domain.refresh import Interval, RefreshBounds


@dataclass(frozen=True)
class HealthStatus:
    checked_at: datetime
    status: Literal["ok"] = "ok"
    service: str = "outage-explorer"


@dataclass(frozen=True)
class EvidenceArtifact:
    name: str
    sha256: str


@dataclass(frozen=True)
class EvidenceBundle:
    manifest_json: str
    manifest_sha256: str
    artifacts: tuple[EvidenceArtifact, ...]
    records: tuple[SourceRecord, ...]
    protected_paths: tuple[str, ...]
    response_total: str | None = None


@dataclass(frozen=True)
class Coverage:
    period: str
    result: DailyResult | None
    excluded_positions: tuple[int, ...]
    identity: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationReport:
    evidence: EvidenceBundle
    coverage: tuple[Coverage, ...]
    ledger: tuple[Disposition, ...]
    counts: tuple[tuple[str, int], ...]
    reason_counts: tuple[tuple[str, int], ...]
    metric: str
    limitations: tuple[str, ...]
    grain: Grain = "national"


@dataclass(frozen=True)
class ReportLocations:
    json: str
    markdown: str


ConnectorOutcome = Literal["candidate_verified", "retained_all_excluded", "failed"]
ConnectorStage = Literal["prior", "retrieval", "modeling", "verification", "complete"]


@dataclass(frozen=True)
class ConnectorInput:
    start: str | None
    end: str | None
    staging: str | None
    prior: str | None = None
    config_path: str | None = None
    fetch_workers: int | None = None
    s3_workers: int | None = None


@dataclass(frozen=True)
class ConnectorArtifactInput:
    operation: Literal["persist", "recover"]
    staging: str | None
    resources: str | None
    config_path: str | None = None
    s3_workers: int | None = None


@dataclass(frozen=True)
class SeedIdentity:
    identity_issuer: str
    identity_subject: str
    email: str
    role: str


@dataclass(frozen=True)
class VerifiedIdentity:
    issuer: str
    subject: str


@dataclass(frozen=True)
class AccessSetupInput:
    operation: Literal["migrate", "seed", "cleanup"]
    manifest: str | None = None


@dataclass(frozen=True)
class LoginRedirect:
    authorization_url: str = field(repr=False)
    browser_binding: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class EstablishedSession:
    token: str = field(repr=False)
    user: SeededUser
    expires_at: datetime
    return_to: str


@dataclass(frozen=True)
class CurrentIdentity:
    user: SeededUser
    expires_at: datetime
    csrf_token: str = field(repr=False)


@dataclass(frozen=True)
class ResourceRequest:
    interval: Interval
    run_id: str
    generation_id: str
    bounds: RefreshBounds
    prior: ResourceBaseline | None = None
    contract_id: str = "eia-nuclear-observations-v1"
    transformation_id: str = "outage-share-exact-v1"

    def __post_init__(self) -> None:
        if (
            self.interval.end - self.interval.start
        ).days + 1 > self.bounds.interval_days or any(
            not value or len(value) > self.bounds.field_chars
            for value in (
                self.run_id,
                self.generation_id,
                self.contract_id,
                self.transformation_id,
            )
        ):
            raise ConnectorConfigurationError("Invalid resource request")
        if self.prior is not None and (
            self.prior.generation_id == self.generation_id
            or self.prior.contract_id != self.contract_id
            or self.prior.transformation_id != self.transformation_id
        ):
            raise ConnectorConfigurationError("Incompatible resource baseline")


@dataclass(frozen=True)
class ResourceReport:
    run_id: str
    generation_id: str
    interval: Interval
    stage: ConnectorStage
    outcome: ConnectorOutcome | None = None
    error: ConnectorFailure | None = None
    candidate: CandidateResult | None = None
    sources: tuple[SourceQuality, ...] = ()
    published: Literal[False] = False


@dataclass(frozen=True)
class ResourceResult:
    report: ResourceReport
    report_written: bool
    local_report: str | None = None
