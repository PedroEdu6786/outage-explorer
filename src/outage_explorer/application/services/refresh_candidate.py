"""Build refresh candidates and validate their identity, coverage and outcome."""

from collections.abc import Callable
from datetime import date
from typing import Literal

from outage_explorer.application.dto import (
    ResourceReport,
    ResourceRequest,
    ResourceResult,
)
from outage_explorer.application.ports.artifacts import ArtifactError
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
    validate_resources,
)
from outage_explorer.application.ports.refresh_execution import AdmittedCandidate
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.publication import RefreshRun
from outage_explorer.domain.refresh import Interval, RefreshBounds


def _coverage(verified: CandidateResult) -> dict[Grain, tuple[date, date]]:
    """Check each resource against its verified row count and coverage."""
    validate_resources(verified.resources)
    if len(verified.summaries) != 3:
        raise ArtifactError("Invalid candidate summary set")
    coverage: dict[Grain, tuple[date, date]] = {}
    for summary in verified.summaries:
        resources = [ref for ref in verified.resources if ref.grain == summary.grain]
        if (
            len(resources) != 1
            or resources[0].row_count != summary.candidate_count
            or summary.first_period is None
            or summary.last_period is None
        ):
            raise ArtifactError("Dataset files or coverage do not match the candidate")
        coverage[summary.grain] = (summary.first_period, summary.last_period)
    if set(coverage) != {grain.value for grain in AnalyticalGrain}:
        raise ArtifactError("Candidate does not cover all three datasets")
    return coverage


class PrepareRefreshCandidate:
    def __init__(
        self,
        candidate: AdmittedCandidate,
        verify: Callable[[CandidateResult, RefreshBounds], None],
        bounds: RefreshBounds,
    ) -> None:
        self._candidate = candidate
        self._verify = verify
        self._bounds = bounds

    def build(
        self, run: RefreshRun, baseline: ResourceBaseline | None
    ) -> ResourceResult:
        request = ResourceRequest(
            interval=Interval(run.configuration.start, run.configuration.end),
            run_id=run.id,
            generation_id=run.id,
            bounds=self._bounds,
            prior=baseline,
        )
        return self._candidate.run(request)

    def verify(
        self,
        run: RefreshRun,
        report: ResourceReport,
    ) -> tuple[CandidateResult, dict[Grain, tuple[date, date]]]:
        verified = report.candidate
        if verified is None:
            raise ArtifactError("Missing verified resource candidate")
        self._verify(verified, self._bounds)
        expected_outcome = "candidate"
        if report.outcome == "retained_all_excluded":
            expected_outcome = "retained_all_excluded"
        if (
            verified.outcome != expected_outcome
            or verified.generation_id != run.id
            or verified.base_generation_id != run.base_generation_id
            or verified.interval
            != Interval(run.configuration.start, run.configuration.end)
            or verified.schema_version != "1"
            or verified.contract_id != ResourceRequest.contract_id
            or verified.transformation_id != ResourceRequest.transformation_id
        ):
            raise ArtifactError("Verified candidate identity mismatch")
        return verified, _coverage(verified)

    def outcome(
        self, run: RefreshRun, report: ResourceReport, verified: CandidateResult
    ) -> Literal["retain", "publish"]:
        self._validate_report_identity(run, report)
        if report.outcome == "retained_all_excluded":
            self._validate_retained_candidate(run, verified)
            return "retain"
        self._validate_publishable_candidate(report, verified)
        return "publish"

    def _validate_report_identity(
        self, run: RefreshRun, report: ResourceReport
    ) -> None:
        if (
            report.run_id != run.id
            or report.generation_id != run.id
            or report.interval
            != Interval(run.configuration.start, run.configuration.end)
        ):
            raise ArtifactError("Candidate identity mismatch")

    def _validate_retained_candidate(
        self, run: RefreshRun, verified: CandidateResult
    ) -> None:
        if (
            run.base_generation_id is None
            or len(verified.summaries) != 3
            or any(
                item.quality.received <= 0
                or item.quality.excluded != item.quality.received
                for item in verified.summaries
            )
        ):
            raise ArtifactError("Invalid retained outcome")

    def _validate_publishable_candidate(
        self, report: ResourceReport, verified: CandidateResult
    ) -> None:
        if (
            report.outcome != "candidate_verified"
            or len(verified.summaries) != 3
            or {item.grain for item in verified.summaries}
            != {grain.value for grain in AnalyticalGrain}
            or any(item.candidate_count <= 0 for item in verified.summaries)
        ):
            raise ArtifactError("Incomplete publishable candidate")
