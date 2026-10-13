"""Bounded contributor candidate creation; deliberately no publication port."""

from dataclasses import replace
from functools import partial

from outage_explorer.application.dto import (
    ConnectorStage,
    ResourceReport,
    ResourceRequest,
    ResourceResult,
)
from outage_explorer.application.errors import ConnectorFailure, ConnectorReportError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBuilder,
    TransientInput,
)
from outage_explorer.application.ports.connector import (
    ConnectorEvents,
    ConnectorSourceFactory,
    ResourceInputs,
    ResourceReports,
)
from outage_explorer.application.ports.connector_workers import ConnectorWorkers
from outage_explorer.application.ports.source import (
    ROUTES,
    SourceError,
    SourceLimitError,
    SourceQuality,
    SourceRequest,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import RefreshInputError, RefreshLimitError


class CreateResourceCandidate:
    """Explicit three-file composition; existing entrypoints switch in phase 4."""

    def __init__(
        self,
        sources: ConnectorSourceFactory,
        inputs: ResourceInputs,
        builder: ResourceBuilder,
        reports: ResourceReports,
        events: ConnectorEvents | None = None,
        workers: ConnectorWorkers | None = None,
    ) -> None:
        self.sources, self.inputs, self.builder, self.reports = (
            sources,
            inputs,
            builder,
            reports,
        )
        self.events, self.workers = events, workers

    def _emit(self, event: str, **details: str | int) -> None:
        if self.events is not None:
            try:
                self.events.emit(event, **details)
            except Exception:
                pass

    def run(self, request: ResourceRequest) -> ResourceResult:
        report = ResourceReport(
            request.run_id, request.generation_id, request.interval, "prior"
        )
        try:
            self.reports.progress(report)
            if request.prior is not None:
                self.inputs.verify_baseline(request.prior, request.bounds)
            report = replace(report, stage="retrieval")
            self.reports.progress(report)
            self._emit("resource_candidate_started", run=request.run_id)
            collected = self._collect_resources(request)
            report = replace(
                report,
                sources=tuple(quality for _, quality in collected),
                stage="modeling",
            )
            self.reports.progress(report)
            candidate = self.builder.build_resources(
                request.generation_id,
                (item for item, _ in collected),
                request.bounds,
                request.prior,
            )
            report = replace(report, stage="verification")
            self.reports.progress(report)
            self._verify_candidate(request, candidate)
            report = replace(
                report,
                stage="complete",
                candidate=candidate,
                outcome="candidate_verified"
                if candidate.outcome == "candidate"
                else "retained_all_excluded",
            )
            self.reports.finish(report)
            self._emit(
                "resource_candidate_complete", run=request.run_id, published="false"
            )
            return ResourceResult(report, True)
        except (Exception, KeyboardInterrupt) as error:
            return self._failed_result(request, report, error)

    def _collect_resources(
        self, request: ResourceRequest
    ) -> tuple[tuple[TransientInput, SourceQuality], ...]:
        tasks = tuple(
            partial(self._collect_resource, request, grain) for grain in ROUTES
        )
        if self.workers is None:
            return tuple(task() for task in tasks)
        return self.workers.run(tasks)

    def _verify_candidate(
        self, request: ResourceRequest, candidate: CandidateResult
    ) -> None:
        self.builder.verify_resources(candidate, request.bounds)
        expected_base = None if request.prior is None else request.prior.generation_id
        if (
            candidate.generation_id != request.generation_id
            or candidate.base_generation_id != expected_base
            or candidate.interval != request.interval
            or candidate.contract_id != request.contract_id
            or candidate.transformation_id != request.transformation_id
        ):
            raise ArtifactError("Resource candidate identity mismatch")
        if self.workers is not None:
            self.workers.run(())

    def _failed_result(
        self,
        request: ResourceRequest,
        report: ResourceReport,
        error: Exception | KeyboardInterrupt,
    ) -> ResourceResult:
        code = _failure_code(error, report.stage)
        failed = replace(report, outcome="failed", error=code, candidate=None)
        self._emit(
            "resource_candidate_failed",
            run=request.run_id,
            stage=failed.stage,
            code=code,
        )
        try:
            self.reports.finish(failed)
        except (Exception, KeyboardInterrupt):
            return ResourceResult(replace(failed, error="report"), False)
        return ResourceResult(failed, True)

    def _collect_resource(
        self, request: ResourceRequest, grain: Grain
    ) -> tuple[TransientInput, SourceQuality]:
        source = self.sources(
            SourceRequest(
                grain,
                request.interval,
                request.run_id,
                f"{request.run_id}-{grain}",
                request.contract_id,
                request.transformation_id,
            )
        )
        item = self.inputs.collect_resources(source.pages())
        quality = source.quality
        if (
            quality is None
            or quality.grain != grain
            or quality.requested != request.interval
            or quality.received != len(item.rows)
            or quality.received == 0
        ):
            raise SourceError("Missing or inconsistent terminal source quality")
        if (
            item.grain != grain
            or item.interval != request.interval
            or item.run_id != request.run_id
            or item.contract_id != request.contract_id
            or item.transformation_id != request.transformation_id
        ):
            raise ArtifactError("Resource source identity mismatch")
        return item, quality


def _failure_code(
    error: Exception | KeyboardInterrupt, stage: ConnectorStage
) -> ConnectorFailure:
    if isinstance(error, ConnectorReportError):
        return "report"
    if isinstance(error, (SourceLimitError, ArtifactLimitError, RefreshLimitError)):
        return "resource"
    if isinstance(error, RepresentationError):
        return "representation"
    if isinstance(error, SourceError):
        return "retrieval"
    if isinstance(error, (ArtifactError, OSError)):
        return "prior_integrity" if stage == "prior" else "artifact_integrity"
    if isinstance(error, RefreshInputError):
        return "unusable_input"
    if isinstance(error, KeyboardInterrupt):
        return "interrupted"
    return "internal"
