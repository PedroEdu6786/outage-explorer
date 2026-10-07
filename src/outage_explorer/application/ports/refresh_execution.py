"""Per-run connector composition and supervised lifetime boundaries."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from outage_explorer.application.dto import ResourceRequest, ResourceResult
from outage_explorer.application.ports.artifacts import ArtifactRef
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
)
from outage_explorer.application.ports.clock import Clock
from outage_explorer.application.ports.connector import (
    DurableResourceReceipt,
)
from outage_explorer.domain.publication import RefreshOwner, RefreshRun
from outage_explorer.domain.refresh import RefreshBounds


class AdmittedCandidate(Protocol):
    def run(self, request: ResourceRequest) -> ResourceResult: ...


@dataclass(frozen=True)
class RefreshConnector:
    candidate: AdmittedCandidate
    bounds: RefreshBounds
    restore: Callable[[DurableResourceReceipt, RefreshBounds], ResourceBaseline]
    verify: Callable[[CandidateResult, RefreshBounds], None]
    addresses: Callable[[str, tuple[ArtifactRef, ...]], tuple[ArtifactRef, ...]]
    persist: Callable[[CandidateResult, RefreshBounds], DurableResourceReceipt]
    clock: Clock


class RefreshConnectorFactory(Protocol):
    def __call__(
        self, run: RefreshRun, owner: RefreshOwner
    ) -> AbstractContextManager[RefreshConnector]: ...


class RefreshLease(Protocol):
    def __call__(self, owner: RefreshOwner) -> AbstractContextManager[None]: ...


class RefreshProcess(Protocol):
    def run(self) -> int: ...
    def close(self) -> None: ...
