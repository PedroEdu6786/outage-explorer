"""Transport-independent application results."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from outage_explorer.domain.observations import (
    DailyResult,
    Disposition,
    Grain,
    SourceRecord,
)


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
