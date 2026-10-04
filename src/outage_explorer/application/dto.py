"""Transport-independent application results."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

# Import only transport-independent contracts; no environment or filesystem types.
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorFailure,
)
from outage_explorer.application.ports.artifacts import StoredObject
from outage_explorer.application.ports.candidates import GrainSummary
from outage_explorer.application.ports.source import SourceQuality
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


@dataclass(frozen=True)
class ConnectorRequest:
    interval: Interval
    run_id: str
    generation_id: str
    bounds: RefreshBounds
    prior: StoredObject | None = None
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
            raise ConnectorConfigurationError("Invalid connector request")


@dataclass(frozen=True)
class ConnectorReport:
    run_id: str
    generation_id: str
    interval: Interval
    stage: ConnectorStage
    outcome: ConnectorOutcome | None = None
    error: ConnectorFailure | None = None
    manifest: StoredObject | None = None
    sources: tuple[SourceQuality, ...] = ()
    models: tuple[GrainSummary, ...] = ()
    published: Literal[False] = False
    limitations: tuple[str, ...] = (
        "Contributor candidate only; no active generation or publication.",
        "Observed order and coverage do not establish upstream completeness or revision recency.",
        "Caller budgets are not measured production limits; live and cloud guarantees remain unverified.",
    )


@dataclass(frozen=True)
class ConnectorResult:
    report: ConnectorReport
    report_written: bool
