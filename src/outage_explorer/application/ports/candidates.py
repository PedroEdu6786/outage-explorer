"""Transport-independent sanitized evidence and candidate contracts.

These local candidates confer no authorization, source-completeness or durable
publication guarantee. The later refresh application owns those boundaries.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import (
    IncomingRow,
    Interval,
    Origin,
    Quality,
    RefreshBounds,
)


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
    transport: tuple[object, ...] = ()


@dataclass(frozen=True)
class EvidenceBundle:
    grain: Grain
    interval: Interval
    raw: tuple[ArtifactRef, ...]
    pages: tuple[ArtifactRef, ...]
    transport: tuple[StoredObject, ...] = ()


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
    first_period: date | None = None
    last_period: date | None = None


@dataclass(frozen=True)
class CandidateManifest:
    generation_id: str
    base_generation_id: str | None
    interval: Interval
    evidence: tuple[EvidenceBundle, ...]
    inherited_evidence: tuple[EvidenceBundle, ...]
    base_modeled: tuple[ArtifactRef, ...]
    modeled: tuple[ArtifactRef, ...]
    public: tuple[ArtifactRef, ...]
    dispositions: tuple[ArtifactRef, ...]
    ledger: tuple[ArtifactRef, ...]
    summaries: tuple[GrainSummary, ...]
    outcome: Literal["candidate", "retained_all_excluded"]
    contract_id: str
    transformation_id: str
    schema_version: str = "2"
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


@dataclass(frozen=True)
class TransientInput:
    """Bounded validated source rows; never a persisted evidence dependency."""

    grain: Grain
    interval: Interval
    rows: tuple[IncomingRow, ...]
    page_count: int
    byte_count: int
    run_id: str
    contract_id: str
    transformation_id: str


def validate_resources(resources: tuple[ArtifactRef, ...]) -> None:
    """Require exactly one nonempty unpartitioned unified file of each grain."""
    if (
        len(resources) != 3
        or {ref.grain for ref in resources} != {"national", "facility", "generator"}
        or len({ref.object.key for ref in resources}) != 3
        or any(
            ref.kind != "resource"
            or ref.partition is not None
            or ref.schema_version != "1"
            or type(ref.row_count) is not int
            or ref.row_count <= 0
            for ref in resources
        )
    ):
        raise ArtifactError("Expected exactly three unified resource files")


@dataclass(frozen=True)
class ResourceBaseline:
    """Exact admitted baseline references, without ancestry or fabricated evidence."""

    generation_id: str
    resources: tuple[ArtifactRef, ...]
    contract_id: str
    transformation_id: str
    schema_version: str = "1"

    def __post_init__(self) -> None:
        validate_resources(self.resources)
        if (
            not self.generation_id
            or not self.contract_id
            or not self.transformation_id
            or self.schema_version != "1"
        ):
            raise ArtifactError("Invalid resource baseline identity")


@dataclass(frozen=True)
class CandidateResult:
    """Three-file result after local semantic verification; no publication right.

    The descriptor contains no verification boolean. Application coordinators
    obtain it from their injected builder; arbitrary construction is not proof
    that input validation or semantic comparison ran.
    """

    generation_id: str
    base_generation_id: str | None
    interval: Interval
    resources: tuple[ArtifactRef, ...]
    summaries: tuple[GrainSummary, ...]
    outcome: Literal["candidate", "retained_all_excluded"]
    contract_id: str
    transformation_id: str
    schema_version: str = "1"

    @property
    def baseline(self) -> ResourceBaseline:
        if self.outcome != "candidate":
            raise ArtifactError("Retained outcome is not a new baseline")
        return ResourceBaseline(
            self.generation_id,
            self.resources,
            self.contract_id,
            self.transformation_id,
            self.schema_version,
        )


class ResourceBuilder(Protocol):
    def build_resources(
        self,
        generation_id: str,
        inputs: Iterable[TransientInput],
        bounds: RefreshBounds,
        prior: ResourceBaseline | None = None,
    ) -> CandidateResult: ...

    def verify_resources(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> None: ...
