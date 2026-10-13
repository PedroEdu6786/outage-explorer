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

_EXPECTED_GRAINS = frozenset(grain.value for grain in AnalyticalGrain)


def _run_interval(run: RefreshRun) -> Interval:
    return Interval(run.configuration.start, run.configuration.end)


def _coverage(verified: CandidateResult) -> dict[Grain, tuple[date, date]]:
    """Check each resource against its verified row count and coverage."""
    validate_resources(verified.resources)
    if len(verified.summaries) != 3:
        raise ArtifactError("Invalid candidate summary set")

    resources_by_grain = {ref.grain: ref for ref in verified.resources}
    coverage: dict[Grain, tuple[date, date]] = {}
    for summary in verified.summaries:
        resource = resources_by_grain.get(summary.grain)
        if (
            resource is None
            or resource.row_count != summary.candidate_count
            or summary.first_period is None
            or summary.last_period is None
        ):
            raise ArtifactError("Dataset files or coverage do not match the candidate")
        coverage[summary.grain] = (summary.first_period, summary.last_period)
    if set(coverage) != _EXPECTED_GRAINS:
        raise ArtifactError("Candidate does not cover all three datasets")
    return coverage


def _require_candidate_identity(
    run: RefreshRun, report: ResourceReport, verified: CandidateResult
) -> None:
    expected_outcome = (
        "retained_all_excluded"
        if report.outcome == "retained_all_excluded"
        else "candidate"
    )
    if verified.outcome != expected_outcome:
        raise ArtifactError("Verified candidate identity mismatch")
    if (
        verified.generation_id != run.id
        or verified.base_generation_id != run.base_generation_id
        or verified.interval != _run_interval(run)
    ):
        raise ArtifactError("Verified candidate identity mismatch")
    if (
        verified.schema_version != "1"
        or verified.contract_id != ResourceRequest.contract_id
        or verified.transformation_id != ResourceRequest.transformation_id
    ):
        raise ArtifactError("Verified candidate identity mismatch")


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
            interval=_run_interval(run),
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
        _require_candidate_identity(run, report, verified)
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
            or report.interval != _run_interval(run)
        ):
            raise ArtifactError("Candidate identity mismatch")

    def _validate_retained_candidate(
        self, run: RefreshRun, verified: CandidateResult
    ) -> None:
        if run.base_generation_id is None or len(verified.summaries) != 3:
            raise ArtifactError("Invalid retained outcome")
        if any(
            summary.quality.received <= 0
            or summary.quality.excluded != summary.quality.received
            for summary in verified.summaries
        ):
            raise ArtifactError("Invalid retained outcome")

    def _validate_publishable_candidate(
        self, report: ResourceReport, verified: CandidateResult
    ) -> None:
        if report.outcome != "candidate_verified" or len(verified.summaries) != 3:
            raise ArtifactError("Incomplete publishable candidate")
        if {item.grain for item in verified.summaries} != _EXPECTED_GRAINS:
            raise ArtifactError("Incomplete publishable candidate")
        if any(item.candidate_count <= 0 for item in verified.summaries):
            raise ArtifactError("Incomplete publishable candidate")
