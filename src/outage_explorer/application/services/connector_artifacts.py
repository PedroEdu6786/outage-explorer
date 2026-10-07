"""Contributor candidate durability; exact local resources and remote receipts."""

from collections.abc import Callable
from dataclasses import dataclass

from outage_explorer.application.dto import (
    ConnectorArtifactInput,
    ConnectorInput,
    ResourceResult,
)
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorDependencyError,
    ConnectorFailure,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.connector import (
    ConnectorEvents,
    DurableResourceReceipt,
)


def _emit(events: ConnectorEvents | None, event: str, **details: str | int) -> None:
    if events is not None:
        try:
            events.emit(event, **details)
        except Exception:
            pass


@dataclass(frozen=True)
class DurableCandidateResult:
    candidate: ResourceResult
    receipt: DurableResourceReceipt | None = None
    error: ConnectorFailure | None = None


class CreateDurableConnectorCandidate:
    """One contributor operation: local verification then complete S3 durability."""

    def __init__(
        self,
        create: Callable[[ConnectorInput], ResourceResult],
        persist: Callable[[ConnectorArtifactInput], DurableResourceReceipt],
        events: ConnectorEvents | None = None,
    ) -> None:
        self.create, self.persist, self.events = create, persist, events

    def execute(self, inputs: ConnectorInput) -> DurableCandidateResult:
        candidate = self.create(inputs)
        report = candidate.report
        if report.outcome in ("failed", "retained_all_excluded"):
            return DurableCandidateResult(candidate)
        if not candidate.report_written:
            return DurableCandidateResult(candidate, error="report")
        try:
            reference = report.candidate
            if reference is None:
                raise ArtifactError("Missing verified local resources")
            _emit(self.events, "candidate_s3_persistence_started", run=report.run_id)
            receipt = self.persist(
                ConnectorArtifactInput(
                    "persist",
                    inputs.staging,
                    candidate.local_report,
                    inputs.config_path,
                    inputs.s3_workers,
                )
            )
            if (
                receipt.generation_id != reference.generation_id
                or receipt.base_generation_id != reference.base_generation_id
                or receipt.interval != reference.interval
                or receipt.contract_id != reference.contract_id
                or receipt.transformation_id != reference.transformation_id
                or receipt.schema_version != reference.schema_version
                or tuple(
                    (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                    for r in receipt.resources
                )
                != tuple(
                    (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                    for r in reference.resources
                )
            ):
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
