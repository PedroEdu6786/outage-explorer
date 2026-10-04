"""Sequential contributor candidate creation; deliberately no publication port."""

from dataclasses import replace

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
from outage_explorer.application.ports.candidates import CandidateBuilder
from outage_explorer.application.ports.connector import (
    ConnectorEvidence,
    ConnectorReports,
    ConnectorSourceFactory,
)
from outage_explorer.application.ports.source import (
    ROUTES,
    SourceError,
    SourceLimitError,
    SourceRequest,
)
from outage_explorer.domain.refresh import RefreshInputError, RefreshLimitError


class CreateConnectorCandidate:
    def __init__(
        self,
        sources: ConnectorSourceFactory,
        evidence: ConnectorEvidence,
        builder: CandidateBuilder,
        reports: ConnectorReports,
    ) -> None:
        self.sources, self.evidence, self.builder, self.reports = (
            sources,
            evidence,
            builder,
            reports,
        )

    def run(self, request: ConnectorRequest) -> ConnectorResult:
        report = ConnectorReport(
            request.run_id, request.generation_id, request.interval, "prior"
        )
        try:
            self.reports.progress(report)
            prior = None
            if request.prior is not None:
                prior = self.evidence.reopen(request.prior, request.bounds)
                if (
                    prior.outcome != "candidate"
                    or prior.generation_id == request.generation_id
                ):
                    raise ArtifactError("Prior must be a different eligible candidate")
            report = replace(report, stage="retrieval")
            self.reports.progress(report)
            bundles = []
            for grain in ROUTES:
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
                bundles.append(bundle)
                report = replace(report, sources=(*report.sources, quality))
                self.reports.progress(report)
            report = replace(report, stage="modeling")
            self.reports.progress(report)
            candidate = self.builder.build(
                request.generation_id, bundles, request.bounds, prior
            )
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
            self.reports.finish(report)
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
            report = replace(report, outcome="failed", error=code, manifest=None)
            try:
                self.reports.finish(report)
            except (Exception, KeyboardInterrupt):
                return ConnectorResult(replace(report, error="report"), False)
            return ConnectorResult(report, True)
