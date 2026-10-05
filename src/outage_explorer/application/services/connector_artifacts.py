"""Connector graph durability and composed candidate-to-S3 execution."""

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from outage_explorer.application.dto import (
    ConnectorArtifactInput,
    ConnectorInput,
    ConnectorResult,
)
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorDependencyError,
    ConnectorFailure,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ExactArtifactStore,
    StoredObject,
)
from outage_explorer.application.ports.candidates import CandidateManifest
from outage_explorer.application.ports.connector import (
    ConnectorEvents,
    ConnectorGraph,
    DurableConnectorReceipt,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.domain.refresh import RefreshBounds


def _emit(events: ConnectorEvents | None, event: str, **details: str | int) -> None:
    if events is not None:
        try:
            events.emit(event, **details)
        except Exception:
            pass  # Diagnostics cannot determine a verified durable outcome.


class PersistConnectorArtifacts:
    def __init__(
        self,
        local: ConnectorGraph,
        durable: ExactArtifactStore,
        events: ConnectorEvents | None = None,
        workers: ConnectorWorkers | None = None,
    ) -> None:
        self.local, self.durable, self.events = local, durable, events
        self.workers = workers

    def execute(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> DurableConnectorReceipt:
        # graph() performs full local replay before any durable transfer.
        _emit(self.events, "s3_persistence_started", manifest=reference.sha256)
        graph = self.local.graph(reference, bounds)
        _emit(
            self.events,
            "local_graph_verified",
            objects=len(graph),
            bytes=sum(item.byte_count for item in graph),
        )
        if not graph or graph[-1] != reference:
            raise ArtifactError("Final graph reference must be the root")
        tasks = (
            partial(self._transfer, dependency, index, len(graph), "dependency")
            for index, dependency in enumerate(graph[:-1], 1)
        )
        if self.workers is None:
            for task in tasks:
                task()
        else:
            self.workers.run(tasks)
        self._transfer(reference, len(graph), len(graph), "final_manifest")
        # The root is last. A durable receipt requires fresh complete readback
        # and schema/value/ledger/replay verification, not just successful PUTs.
        _emit(self.events, "durable_graph_readback_started", manifest=reference.sha256)
        self.local.verify_remote(reference, self.durable, bounds)
        if self.workers is not None:
            self.workers.run(())
        _emit(
            self.events,
            "s3_persistence_verified",
            manifest=reference.sha256,
            published="false",
        )
        return DurableConnectorReceipt(
            reference, len(graph), sum(item.byte_count for item in graph)
        )

    def _transfer(
        self, dependency: StoredObject, index: int, count: int, role: str
    ) -> None:
        _emit(
            self.events,
            "s3_transfer_started",
            object=index,
            total=count,
            sha256=dependency.sha256,
            bytes=dependency.byte_count,
            role=role,
        )
        self.durable.put_exact(dependency, self.local.read(dependency))


class RecoverConnectorArtifacts:
    def __init__(
        self,
        local: ConnectorGraph,
        durable: ExactArtifactStore,
        events: ConnectorEvents | None = None,
    ) -> None:
        self.local, self.durable, self.events = local, durable, events

    def execute(
        self, reference: StoredObject, bounds: RefreshBounds
    ) -> CandidateManifest:
        _emit(
            self.events,
            "recovery_started",
            manifest=reference.sha256,
            source="configured_s3",
            eia="disabled",
        )
        candidate = self.local.restore(reference, self.durable, bounds)
        _emit(
            self.events,
            "recovery_verified",
            manifest=reference.sha256,
            published="false",
        )
        return candidate


@dataclass(frozen=True)
class DurableCandidateResult:
    candidate: ConnectorResult
    receipt: DurableConnectorReceipt | None = None
    error: ConnectorFailure | None = None


class CreateDurableConnectorCandidate:
    """One contributor operation: local verification then complete S3 durability."""

    def __init__(
        self,
        create: Callable[[ConnectorInput], ConnectorResult],
        persist: Callable[[ConnectorArtifactInput], DurableConnectorReceipt],
        events: ConnectorEvents | None = None,
    ) -> None:
        self.create, self.persist, self.events = create, persist, events

    def execute(self, inputs: ConnectorInput) -> DurableCandidateResult:
        candidate = self.create(inputs)
        report = candidate.report
        if report.outcome == "failed":
            return DurableCandidateResult(candidate)
        if not candidate.report_written:
            return DurableCandidateResult(candidate, error="report")
        try:
            reference = report.manifest
            if reference is None:
                raise ArtifactError("Missing verified local manifest")
            _emit(self.events, "candidate_s3_persistence_started", run=report.run_id)
            receipt = self.persist(
                ConnectorArtifactInput(
                    "persist",
                    inputs.staging,
                    f"{reference.sha256}:{reference.byte_count}",
                    inputs.config_path,
                    inputs.s3_workers,
                )
            )
            if receipt.manifest != reference:
                raise ArtifactError("Durable receipt differs from local candidate")
            _emit(
                self.events,
                "candidate_s3_complete",
                run=report.run_id,
                published="false",
            )
            return DurableCandidateResult(candidate, receipt)
        except (Exception, KeyboardInterrupt) as error:
            code: ConnectorFailure
            if isinstance(error, ConnectorConfigurationError):
                code = "configuration"
            elif isinstance(error, ConnectorDependencyError):
                code = "aws_dependency"
            elif isinstance(error, ArtifactLimitError):
                code = "resource"
            elif isinstance(error, ArtifactError):
                code = "artifact_integrity"
            elif isinstance(error, KeyboardInterrupt):
                code = "interrupted"
            else:
                code = "internal"
            _emit(self.events, "candidate_s3_failed", run=report.run_id, code=code)
            return DurableCandidateResult(candidate, error=code)
