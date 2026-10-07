"""Bounded contributor candidate creation; deliberately no publication port."""

from dataclasses import replace
from functools import partial

from outage_explorer.application.dto import (
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
from outage_explorer.application.ports.candidates import ResourceBuilder, TransientInput
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
            tasks = tuple(
                partial(self._collect_resource, request, grain) for grain in ROUTES
            )
            collected = (
                tuple(task() for task in tasks)
                if self.workers is None
                else self.workers.run(tasks)
            )
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
            self.builder.verify_resources(candidate, request.bounds)
            if (
                candidate.generation_id != request.generation_id
                or candidate.base_generation_id
                != (None if request.prior is None else request.prior.generation_id)
                or candidate.interval != request.interval
                or candidate.contract_id != request.contract_id
                or candidate.transformation_id != request.transformation_id
            ):
                raise ArtifactError("Resource candidate identity mismatch")
            if self.workers is not None:
                self.workers.run(())
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
            if isinstance(error, ConnectorReportError):
                code: ConnectorFailure = "report"
            elif isinstance(
                error, (SourceLimitError, ArtifactLimitError, RefreshLimitError)
            ):
                code = "resource"
            elif isinstance(error, RepresentationError):
                code = "representation"
            elif isinstance(error, SourceError):
                code = "retrieval"
            elif isinstance(error, (ArtifactError, OSError)):
                code = (
                    "prior_integrity"
                    if report.stage == "prior"
                    else "artifact_integrity"
                )
            elif isinstance(error, RefreshInputError):
                code = "unusable_input"
            elif isinstance(error, KeyboardInterrupt):
                code = "interrupted"
            else:
                code = "internal"
            report = replace(report, outcome="failed", error=code, candidate=None)
            self._emit(
                "resource_candidate_failed",
                run=request.run_id,
                stage=report.stage,
                code=code,
            )
            try:
                self.reports.finish(report)
            except (Exception, KeyboardInterrupt):
                return ResourceResult(replace(report, error="report"), False)
            return ResourceResult(report, True)

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
