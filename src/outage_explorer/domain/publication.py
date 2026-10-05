"""Immutable durable refresh snapshots and publication references."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from outage_explorer.domain.access import AnalyticalGrain

INITIAL_START = date(2026, 4, 2)
INITIAL_END = date(2026, 10, 1)


class RunStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETAINED = "retained"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    PUBLICATION_UNKNOWN = "publication_unknown"

    @property
    def terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.RETAINED, self.FAILED, self.INTERRUPTED}


class PublicationState(StrEnum):
    PENDING = "pending"
    PUBLISHED = "published"
    NOT_PUBLISHED = "not_published"
    UNKNOWN = "unknown"


class RefreshStage(StrEnum):
    QUEUED = "queued"
    RETRIEVING = "retrieving"
    MODELING = "modeling"
    PERSISTING = "persisting"
    VERIFYING = "verifying"
    PUBLISHING = "publishing"
    FINISHED = "finished"


@dataclass(frozen=True)
class RefreshConfiguration:
    start: date
    end: date
    max_interval_days: int
    source_interval_days: int
    model_interval_days: int
    candidate_seconds: int
    persistence_seconds: int
    contract_version: str = "v1"

    def validate(self, *, initial: bool) -> None:
        limits = (
            self.max_interval_days,
            self.source_interval_days,
            self.model_interval_days,
            self.candidate_seconds,
            self.persistence_seconds,
        )
        if (
            any(type(value) is not int or value <= 0 for value in limits)
            or self.start > self.end
            or (self.end - self.start).days + 1 > min(limits[:3])
            or self.max_interval_days > 183
            or self.contract_version != "v1"
            or initial
            and (self.start, self.end) != (INITIAL_START, INITIAL_END)
        ):
            raise ValueError("Invalid refresh configuration")


@dataclass(frozen=True)
class DatasetSummary:
    grain: AnalyticalGrain
    schema_version: str
    rows: int
    start: date
    end: date


@dataclass(frozen=True)
class PublishedGeneration:
    id: str
    run_id: str
    base_generation_id: str | None
    manifest_key: str
    manifest_digest: str
    verification_version: str
    verified_at: datetime
    datasets: tuple[DatasetSummary, ...]

    def validate(self) -> None:
        if (
            {item.grain for item in self.datasets} != set(AnalyticalGrain)
            or len(self.datasets) != 3
            or any(
                item.rows <= 0 or item.start > item.end or item.schema_version != "v1"
                for item in self.datasets
            )
            or self.verification_version != "v1"
            or len(self.manifest_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.manifest_digest)
            or not self.manifest_key
            or len(self.manifest_key) > 2048
            or self.verified_at.tzinfo is None
        ):
            raise ValueError("Invalid verified generation")


@dataclass(frozen=True)
class RefreshRun:
    id: str
    requester_id: str
    key_digest: str
    request_identity: str
    configuration: RefreshConfiguration
    base_generation_id: str | None
    status: RunStatus
    stage: RefreshStage
    admitted_at: datetime
    updated_at: datetime
    epoch: int | None
    generation_id: str | None
    publication: PublicationState
    quality_json: str | None
    failure: str | None
    no_publication_reason: str | None

    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def grains(self) -> tuple[AnalyticalGrain, ...]:
        return tuple(AnalyticalGrain)


@dataclass(frozen=True)
class RefreshOwner:
    run_id: str
    identity: str
    epoch: int
