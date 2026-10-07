"""Local contributor connector seams, independent of storage and HTTP libraries."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

from outage_explorer.application.dto import ResourceReport
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
    SanitizedPage,
    TransientInput,
    validate_resources,
)
from outage_explorer.application.ports.source import SourcePages, SourceRequest
from outage_explorer.domain.refresh import Interval, RefreshBounds


class ConnectorEvents(Protocol):
    """Best-effort diagnostics: fixed event names and safe counts/identities only."""

    def emit(self, event: str, **details: str | int) -> None: ...


class ConnectorSourceFactory(Protocol):
    def __call__(self, request: SourceRequest) -> SourcePages: ...


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
    interval: Interval
    contract_id: str
    transformation_id: str
    base_generation_id: str | None
    schema_version: str = "1"

    def __post_init__(self) -> None:
        validate_resources(self.resources)
        if (
            not isinstance(self.generation_id, str)
            or not self.generation_id
            or not isinstance(self.contract_id, str)
            or not self.contract_id
            or not isinstance(self.transformation_id, str)
            or not self.transformation_id
            or not isinstance(self.interval, Interval)
            or (
                self.base_generation_id is not None
                and (
                    not isinstance(self.base_generation_id, str)
                    or not self.base_generation_id
                )
            )
            or self.schema_version != "1"
            or self.base_generation_id == self.generation_id
        ):
            raise ArtifactError("Missing durable generation identity")


class RecoveryStaging(Protocol):
    def __enter__(self) -> None: ...
    def __exit__(
        self, exc_type: Any, exc_value: Any, traceback: Any
    ) -> bool | None: ...


class ResourceTransfers(Protocol):
    def recovery_staging(self, size: int) -> RecoveryStaging: ...

    def addresses(
        self, generation_id: str, resources: tuple[ArtifactRef, ...]
    ) -> tuple[ArtifactRef, ...]: ...
    def validate_receipt(self, receipt: DurableResourceReceipt) -> None: ...
    def put_verified(
        self, reference: ArtifactRef, chunks: Iterable[bytes]
    ) -> ArtifactRef: ...
    def read(self, reference: StoredObject) -> Iterator[bytes]: ...


class ResourceFiles(Protocol):
    def verify_candidate(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> None: ...
    def read(self, reference: StoredObject) -> Iterator[bytes]: ...
    def restore_resources(
        self,
        receipt: DurableResourceReceipt,
        source: ResourceTransfers,
        bounds: RefreshBounds,
    ) -> ResourceBaseline: ...
