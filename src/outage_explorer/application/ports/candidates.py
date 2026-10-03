"""Transport-independent sanitized evidence and candidate contracts.

These local candidates confer no authorization, source-completeness or durable
publication guarantee. The later refresh application owns those boundaries.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol

from outage_explorer.application.ports.artifacts import ArtifactRef, StoredObject
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import Interval, Origin, Quality, RefreshBounds


@dataclass(frozen=True)
class SanitizedPage:
    """Already sanitized JSON values; origin identifies row zero of this page.

    Offset/attempt describe the accepted request. Failed transport attempts and
    sanitization are the source adapter's responsibility, not this storage API.
    """

    origin: Origin
    interval: Interval
    offset: int
    length: int
    attempt: int
    source_total: str
    route: str
    parameters: object
    metadata: object
    api_version: str
    values: tuple[object, ...]


@dataclass(frozen=True)
class EvidenceBundle:
    grain: Grain
    interval: Interval
    raw: tuple[ArtifactRef, ...]
    pages: tuple[ArtifactRef, ...]


@dataclass(frozen=True)
class GrainSummary:
    grain: Grain
    quality: Quality
    active_count: int
    candidate_count: int
    retained_invalid: int
    retained_absent: int
    carried_outside_interval: int
    observed_entities: int
    observed_dates: int
    usable_dates: int


@dataclass(frozen=True)
class CandidateManifest:
    generation_id: str
    base_generation_id: str | None
    interval: Interval
    evidence: tuple[EvidenceBundle, ...]
    inherited_evidence: tuple[EvidenceBundle, ...]
    base_modeled: tuple[ArtifactRef, ...]
    modeled: tuple[ArtifactRef, ...]
    dispositions: tuple[ArtifactRef, ...]
    ledger: tuple[ArtifactRef, ...]
    summaries: tuple[GrainSummary, ...]
    outcome: Literal["candidate", "retained_all_excluded"]
    contract_id: str
    transformation_id: str
    schema_version: str = "1"
    manifest_object: StoredObject | None = None
    base_manifest_object: StoredObject | None = None


class CandidateBuilder(Protocol):
    def build(
        self,
        generation_id: str,
        evidence: Iterable[EvidenceBundle],
        bounds: RefreshBounds,
        prior: CandidateManifest | None = None,
    ) -> CandidateManifest: ...

    def verify(self, candidate: CandidateManifest, bounds: RefreshBounds) -> None: ...
