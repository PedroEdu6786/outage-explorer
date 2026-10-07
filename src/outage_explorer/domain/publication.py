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
    s3_workers: int = 3

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
            or self.contract_version != "v1"
            or type(self.s3_workers) is not int
            or not 1 <= self.s3_workers <= 3
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
    object_key: str | None = None
    sha256: str | None = None
    byte_count: int | None = None

    def validate(self) -> None:
        if (
            not isinstance(self.grain, AnalyticalGrain)
            or type(self.rows) is not int
            or self.rows <= 0
            or type(self.start) is not date
            or type(self.end) is not date
            or self.start > self.end
            or self.schema_version != "v1"
        ):
            raise ValueError("Invalid dataset summary")
        if (
            not isinstance(self.object_key, str)
            or not self.object_key
            or len(self.object_key.encode("utf-8")) > 1024
            or self.object_key.startswith("/")
            or any(part in ("", ".", "..") for part in self.object_key.split("/"))
            or any(
                not (char.isascii() and (char.isalnum() or char in "_-/."))
                for char in self.object_key
            )
            or not isinstance(self.sha256, str)
            or len(self.sha256) != 64
            or any(char not in "0123456789abcdef" for char in self.sha256)
            or type(self.byte_count) is not int
            or self.byte_count <= 0
        ):
            raise ValueError("Invalid exact dataset resource descriptor")


@dataclass(frozen=True)
class ResourcePublishedGeneration:
    """Exact three-file publication metadata; no manifest or durability claim.

    Constructed from an admitted run and verified durable receipt by the refresh
    coordinator. This pure value contract does not prove storage verification or
    grant authority to change an active publication pointer.
    """

    id: str
    run_id: str
    base_generation_id: str | None
    verification_version: str
    verified_at: datetime
    datasets: tuple[DatasetSummary, ...]

    def validate(self) -> None:
        if (
            not isinstance(self.id, str)
            or not self.id
            or not isinstance(self.run_id, str)
            or not self.run_id
            or (
                self.base_generation_id is not None
                and (
                    not isinstance(self.base_generation_id, str)
                    or not self.base_generation_id
                )
            )
            or self.base_generation_id == self.id
            or self.verification_version != "v1"
            or not isinstance(self.verified_at, datetime)
            or self.verified_at.tzinfo is None
            or self.verified_at.utcoffset() is None
            or len(self.datasets) != 3
            or {item.grain for item in self.datasets} != set(AnalyticalGrain)
        ):
            raise ValueError("Invalid verified resource generation")
        for item in self.datasets:
            item.validate()
        filenames = {
            AnalyticalGrain.NATIONAL: "national",
            AnalyticalGrain.FACILITY: "facilities",
            AnalyticalGrain.GENERATOR: "generators",
        }
        for item in self.datasets:
            suffix = f"generations/{self.id}/{filenames[item.grain]}.parquet"
            if item.object_key is None or not item.object_key.endswith("/" + suffix):
                raise ValueError("Resource generation/grain address mismatch")
        if len({item.object_key for item in self.datasets}) != 3:
            raise ValueError("Resource generation requires three distinct exact keys")


@dataclass(frozen=True)
class RefreshRun:
    id: str
    requester_id: str
    key_digest: str
    configuration: RefreshConfiguration
    base_generation_id: str | None
    status: RunStatus
    stage: RefreshStage
    admitted_at: datetime
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
