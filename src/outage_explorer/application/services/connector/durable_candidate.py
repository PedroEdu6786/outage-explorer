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
    ArtifactRef,
)
from outage_explorer.application.ports.candidates import CandidateResult
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


def _resource_contents(
    resources: tuple[ArtifactRef, ...],
) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(
        (item.grain, item.object.sha256, item.object.byte_count, item.row_count)
        for item in resources
    )


def _verify_receipt(
    receipt: DurableResourceReceipt, candidate: CandidateResult
) -> None:
    receipt_identity = (
        receipt.generation_id,
        receipt.base_generation_id,
        receipt.interval,
        receipt.contract_id,
        receipt.transformation_id,
        receipt.schema_version,
    )
    candidate_identity = (
        candidate.generation_id,
        candidate.base_generation_id,
        candidate.interval,
        candidate.contract_id,
        candidate.transformation_id,
        candidate.schema_version,
    )
    if receipt_identity != candidate_identity or _resource_contents(
        receipt.resources
    ) != _resource_contents(candidate.resources):
        raise ArtifactError("Durable receipt differs from local candidate")


def _failure_code(error: BaseException) -> ConnectorFailure:
    if isinstance(error, ConnectorConfigurationError):
        return "configuration"
    if isinstance(error, ConnectorDependencyError):
        return "aws_dependency"
    if isinstance(error, ArtifactLimitError):
        return "resource"
    if isinstance(error, ArtifactError):
        return "artifact_integrity"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    return "internal"


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
            receipt = self._persist_candidate(inputs, candidate)
        except (Exception, KeyboardInterrupt) as error:
            code = _failure_code(error)
            _emit(self.events, "candidate_s3_failed", run=report.run_id, code=code)
            return DurableCandidateResult(candidate, error=code)
        _emit(
            self.events,
            "candidate_s3_complete",
            run=report.run_id,
            published="false",
        )
        return DurableCandidateResult(candidate, receipt)

    def _persist_candidate(
        self, inputs: ConnectorInput, candidate: ResourceResult
    ) -> DurableResourceReceipt:
        reference = candidate.report.candidate
        if reference is None:
            raise ArtifactError("Missing verified local resources")
        _emit(
            self.events, "candidate_s3_persistence_started", run=candidate.report.run_id
        )
        receipt = self.persist(
            ConnectorArtifactInput(
                "persist",
                inputs.staging,
                candidate.local_report,
                inputs.config_path,
                inputs.s3_workers,
            )
        )
        _verify_receipt(receipt, reference)
        return receipt
