"""Per-run connector composition and supervised lifetime boundaries."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from outage_explorer.application.dto import (
    ResourceReport,
    ResourceRequest,
    ResourceResult,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
)
from outage_explorer.application.ports.connector import (
    DurableResourceReceipt,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.publication import (
    RefreshOwner,
    RefreshRun,
    ResourcePublishedGeneration,
)


class AdmittedCandidate(Protocol):
    def run(self, request: ResourceRequest) -> ResourceResult: ...


class RefreshBaseline(Protocol):
    def restore(self, run: RefreshRun) -> ResourceBaseline | None: ...


class RefreshCandidate(Protocol):
    def build(
        self, run: RefreshRun, baseline: ResourceBaseline | None
    ) -> ResourceResult: ...

    def verify(
        self, run: RefreshRun, report: ResourceReport
    ) -> tuple[CandidateResult, dict[Grain, tuple[date, date]]]: ...

    def outcome(
        self, run: RefreshRun, report: ResourceReport, verified: CandidateResult
    ) -> Literal["retain", "publish"]: ...


class RefreshPublication(Protocol):
    def persist(self, verified: CandidateResult) -> DurableResourceReceipt: ...

    def generation(
        self,
        run: RefreshRun,
        verified: CandidateResult,
        receipt: DurableResourceReceipt,
        coverage: dict[Grain, tuple[date, date]],
    ) -> ResourcePublishedGeneration: ...


@dataclass(frozen=True)
class RefreshPipeline:
    """Services sharing one run's bounded resources and cleanup lifetime."""

    baseline: RefreshBaseline
    candidate: RefreshCandidate
    publication: RefreshPublication


class RefreshPipelineFactory(Protocol):
    def __call__(
        self, run: RefreshRun, owner: RefreshOwner
    ) -> AbstractContextManager[RefreshPipeline]: ...


class RefreshLease(Protocol):
    def __call__(self, owner: RefreshOwner) -> AbstractContextManager[None]: ...


class RefreshProcess(Protocol):
    def run(self) -> int: ...
    def close(self) -> None: ...
