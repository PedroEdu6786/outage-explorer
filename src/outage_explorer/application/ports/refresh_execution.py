"""Per-run connector composition and supervised lifetime boundaries."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from outage_explorer.application.dto import ConnectorRequest, ConnectorResult
from outage_explorer.application.ports.artifacts import StoredObject
from outage_explorer.application.ports.candidates import CandidateManifest
from outage_explorer.application.ports.clock import Clock
from outage_explorer.application.ports.connector import (
    ConnectorGraph,
    DurableConnectorReceipt,
)
from outage_explorer.domain.publication import RefreshOwner, RefreshRun
from outage_explorer.domain.refresh import RefreshBounds


class AdmittedCandidate(Protocol):
    def run(self, request: ConnectorRequest) -> ConnectorResult: ...


@dataclass(frozen=True)
class RefreshConnector:
    candidate: AdmittedCandidate
    graph: ConnectorGraph
    bounds: RefreshBounds
    restore: Callable[[StoredObject, RefreshBounds], CandidateManifest]
    reopen: Callable[[StoredObject, RefreshBounds], CandidateManifest]
    persist: Callable[[StoredObject, RefreshBounds], DurableConnectorReceipt]
    reference: Callable[[str, str], StoredObject]
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
