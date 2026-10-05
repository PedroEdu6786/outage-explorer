"""Bounded contributor candidate creation; deliberately no publication port."""

from dataclasses import replace
from functools import partial

from outage_explorer.application.dto import (
    ConnectorReport,
    ConnectorRequest,
    ConnectorResult,
)
from outage_explorer.application.errors import ConnectorFailure, ConnectorReportError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import (
    CandidateBuilder,
    EvidenceBundle,
)
from outage_explorer.application.ports.connector import (
    ConnectorEvents,
    ConnectorEvidence,
    ConnectorReports,
    ConnectorSourceFactory,
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


class CreateConnectorCandidate:
    def __init__(
        self,
        sources: ConnectorSourceFactory,
        evidence: ConnectorEvidence,
        builder: CandidateBuilder,
        reports: ConnectorReports,
        events: ConnectorEvents | None = None,
        workers: ConnectorWorkers | None = None,
    ) -> None:
        self.sources, self.evidence, self.builder, self.reports = (
            sources,
            evidence,
            builder,
            reports,
        )

        self.events, self.workers = events, workers

    def _emit(self, event: str, **details: str | int) -> None:
        # Diagnostics never determine candidate success or change merge policy.
        if self.events is not None:
            try:
                self.events.emit(event, **details)
            except Exception:
                pass

    def run(self, request: ConnectorRequest) -> ConnectorResult:
        report = ConnectorReport(
            request.run_id, request.generation_id, request.interval, "prior"
        )
        try:
            self._emit(
                "candidate_started",
                run=request.run_id,
                start=request.interval.start.isoformat(),
                end=request.interval.end.isoformat(),
            )
            self.reports.progress(report)
            prior = None
            if request.prior is not None:
                self._emit("prior_verification_started", run=request.run_id)
                prior = self.evidence.reopen(request.prior, request.bounds)
                if (
                    prior.outcome != "candidate"
                    or prior.generation_id == request.generation_id
                ):
                    raise ArtifactError("Prior must be a different eligible candidate")
            self._emit(
                "prior_ready",
                run=request.run_id,
                mode="initial" if prior is None else "compare_with_prior",
            )
            report = replace(report, stage="retrieval")
            self.reports.progress(report)
            tasks = tuple(partial(self._collect, request, grain) for grain in ROUTES)
            collected = (
                tuple(task() for task in tasks)
                if self.workers is None
                else self.workers.run(tasks)
            )
            bundles = [bundle for bundle, _ in collected]
            for _, quality in collected:
                report = replace(report, sources=(*report.sources, quality))
                self.reports.progress(report)
            report = replace(report, stage="modeling")
            self.reports.progress(report)
            self._emit(
                "comparison_started",
                run=request.run_id,
                policy="last_valid_source_order_wins;retain_invalid_or_absent_prior",
            )
            candidate = self.builder.build(
                request.generation_id, bundles, request.bounds, prior
            )
            for summary in candidate.summaries:
                model_quality = summary.quality
                self._emit(
                    "comparison_complete",
                    run=request.run_id,
                    grain=summary.grain,
                    received=model_quality.received,
                    selected=model_quality.selected,
                    skipped_invalid=model_quality.excluded,
                    skipped_duplicates=model_quality.duplicate,
                    conflicts_superseded=model_quality.superseded,
                    retained_invalid=summary.retained_invalid,
                    retained_absent=summary.retained_absent,
                    output=summary.candidate_count,
                )
                for reason, count in model_quality.reason_counts:
                    # Only contract reason codes are diagnostic; field names may be untrusted.
                    self._emit(
                        "rows_skipped",
                        run=request.run_id,
                        grain=summary.grain,
                        reason=reason.code,
                        occurrences=count,
                    )
            self._emit("candidate_verification_started", run=request.run_id)
            report = replace(report, stage="verification")
            self.reports.progress(report)
            self.builder.verify(candidate, request.bounds)
            if candidate.manifest_object is None:
                raise ArtifactError("Candidate has no persisted manifest")
            reopened = self.evidence.reopen(candidate.manifest_object, request.bounds)
            if reopened != candidate:
                raise ArtifactError("Reopened candidate differs")
            report = replace(
                report,
                stage="complete",
                outcome="candidate_verified"
                if candidate.outcome == "candidate"
                else "retained_all_excluded",
                manifest=candidate.manifest_object,
                models=candidate.summaries,
            )
            if self.workers is not None:
                self.workers.run(())
            self.reports.finish(report)
            self._emit(
                "candidate_complete",
                run=request.run_id,
                outcome=report.outcome or "failed",
                published="false",
            )
            return ConnectorResult(report, True)
        except (Exception, KeyboardInterrupt) as error:
            code: ConnectorFailure
            if isinstance(error, ConnectorReportError):
                code = "report"
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
            self._emit(
                "candidate_failed", run=request.run_id, stage=report.stage, code=code
            )
            report = replace(report, outcome="failed", error=code, manifest=None)
            try:
                self.reports.finish(report)
            except (Exception, KeyboardInterrupt):
                self._emit(
                    "candidate_failed",
                    run=request.run_id,
                    stage="report",
                    code="report",
                )
                return ConnectorResult(replace(report, error="report"), False)
            return ConnectorResult(report, True)

    def _collect(
        self, request: ConnectorRequest, grain: Grain
    ) -> tuple[EvidenceBundle, SourceQuality]:
        self._emit(
            "collection_started",
            run=request.run_id,
            grain=grain,
            source="EIA",
            storage="local_parquet",
        )
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
        bundle = self.evidence.write(source.pages())
        quality = source.quality
        if (
            quality is None
            or quality.grain != grain
            or quality.requested != request.interval
            or quality.received != sum(ref.row_count for ref in bundle.raw)
        ):
            raise SourceError("Missing or inconsistent terminal source quality")
        if quality.received == 0:
            raise SourceError("Required route is empty")
        self._emit(
            "collection_complete",
            run=request.run_id,
            grain=grain,
            received=quality.received,
            raw_objects=len(bundle.raw),
            page_objects=len(bundle.pages),
        )
        return bundle, quality
