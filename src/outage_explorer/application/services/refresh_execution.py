"""Execute only committed claims using frozen inputs and verified durable resource files."""

from datetime import date

from outage_explorer.application.dto import ResourceReport, ResourceRequest
from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
    validate_resources,
)
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import (
    RefreshConnector,
    RefreshConnectorFactory,
    RefreshLease,
)
from outage_explorer.application.refresh_outcomes import quality_json, safe_failure
from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.publication import (
    DatasetSummary,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    ResourcePublishedGeneration,
    RunStatus,
)
from outage_explorer.domain.refresh import Interval


class RefreshReports:
    """Connector progress adapter; durable status contains only safe bounded counts."""

    def __init__(self, store: RefreshStore, owner: RefreshOwner) -> None:
        self.store, self.owner = store, owner

    def progress(self, report: ResourceReport) -> None:
        stage = {
            "prior": RefreshStage.RETRIEVING,
            "retrieval": RefreshStage.RETRIEVING,
            "modeling": RefreshStage.MODELING,
            "verification": RefreshStage.VERIFYING,
            "complete": RefreshStage.VERIFYING,
        }[report.stage]
        self.store.progress(self.owner, stage, quality_json(report))

    def finish(self, report: ResourceReport) -> None:
        self.store.progress(self.owner, RefreshStage.VERIFYING, quality_json(report))


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


class RefreshExecution:
    def __init__(
        self,
        store: RefreshStore,
        publication: ResourcePublicationStore,
        factory: RefreshConnectorFactory,
    ) -> None:
        self.store, self.publication, self.factory = store, publication, factory

    def execute(self, owner: RefreshOwner) -> RefreshRun:
        """Restore, build, verify and persist a candidate before publishing it."""
        run = self._load_claimed_run(owner)
        report_json = None
        publication_started = False
        try:
            # Validate complete ownership and the live lease before baseline/source I/O.
            self.store.progress(owner, RefreshStage.RETRIEVING)
            run.configuration.validate(initial=run.base_generation_id is None)
            with self.factory(run, owner) as connector:
                baseline = self._restore_baseline(run, connector)
                request = ResourceRequest(
                    interval=Interval(run.configuration.start, run.configuration.end),
                    run_id=run.id,
                    generation_id=run.id,
                    bounds=connector.bounds,
                    prior=baseline,
                )
                result = connector.candidate.run(request)
                report = result.report
                report_json = quality_json(report)
                if report.outcome == "failed" or not result.report_written:
                    return self.store.finish(
                        owner, RunStatus.FAILED, report_json, report.error or "report"
                    )

                verified = self._verify_candidate(run, connector, request, report)
                coverage = _coverage(verified)
                report_json = quality_json(report, coverage)
                self._validate_report_identity(request, report)

                if report.outcome == "retained_all_excluded":
                    self._validate_retained_candidate(run, verified)
                    return self.store.finish(owner, RunStatus.RETAINED, report_json)

                self._validate_publishable_candidate(report, verified)
                self.store.progress(owner, RefreshStage.PERSISTING, report_json)
                receipt = self._persist_candidate(connector, verified)

                self.store.progress(owner, RefreshStage.PUBLISHING, report_json)
                generation = self._build_publication_generation(
                    run, connector, verified, receipt, coverage
                )
                publication_started = True
                return self.publication.publish(owner, generation, report_json)
        except (StaleRefreshOwnerError, AccessStoreError):
            raise  # Never turn loss of ownership or uncertainty into a failed outcome.
        except Exception as error:
            if publication_started:
                raise  # An ambiguous publication must be reconciled, never overwritten.
            return self.store.finish(
                owner, RunStatus.FAILED, report_json, safe_failure(error)
            )

    def _load_claimed_run(self, owner: RefreshOwner) -> RefreshRun:
        run = self.store.get_run(owner.run_id)
        if run is None:
            raise StaleRefreshOwnerError("Missing committed claim")
        if run.status is not RunStatus.RUNNING:
            raise StaleRefreshOwnerError("Missing committed claim")
        if run.epoch != owner.epoch:
            raise StaleRefreshOwnerError("Missing committed claim")
        return run

    def _restore_baseline(
        self, run: RefreshRun, connector: RefreshConnector
    ) -> ResourceBaseline | None:
        base = self.publication.active_generation()
        if (None if base is None else base.id) != run.base_generation_id:
            raise StaleRefreshOwnerError("Pinned base changed")
        if base is None:
            return None

        base_run = self.store.get_run(base.run_id)
        if base_run is None or base_run.generation_id != base.id:
            raise ArtifactError("Pinned base run identity mismatch")
        descriptors = tuple(
            ArtifactRef(
                StoredObject(
                    item.object_key or "",
                    item.sha256 or "",
                    item.byte_count or 0,
                ),
                "resource",
                item.grain.value,
                None,
                item.rows,
            )
            for item in base.datasets
        )
        prior = connector.restore(
            DurableResourceReceipt(
                base.id,
                descriptors,
                Interval(base_run.configuration.start, base_run.configuration.end),
                "eia-nuclear-observations-v1",
                "outage-share-exact-v1",
                base.base_generation_id,
            ),
            connector.bounds,
        )
        if (
            prior.generation_id != base.id
            or prior.contract_id != "eia-nuclear-observations-v1"
            or prior.transformation_id != "outage-share-exact-v1"
            or tuple(
                (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                for r in prior.resources
            )
            != tuple(
                (r.grain, r.object.sha256, r.object.byte_count, r.row_count)
                for r in descriptors
            )
        ):
            raise ArtifactError("Pinned base identity mismatch")
        return prior

    def _verify_candidate(
        self,
        run: RefreshRun,
        connector: RefreshConnector,
        request: ResourceRequest,
        report: ResourceReport,
    ) -> CandidateResult:
        verified = report.candidate
        if verified is None:
            raise ArtifactError("Missing verified resource candidate")
        connector.verify(verified, connector.bounds)
        expected_outcome = "candidate"
        if report.outcome == "retained_all_excluded":
            expected_outcome = "retained_all_excluded"
        if (
            verified.outcome != expected_outcome
            or verified.generation_id != run.id
            or verified.base_generation_id != run.base_generation_id
            or verified.interval != request.interval
            or verified.schema_version != "1"
            or verified.contract_id != request.contract_id
            or verified.transformation_id != request.transformation_id
        ):
            raise ArtifactError("Verified candidate identity mismatch")
        return verified

    def _validate_report_identity(
        self, request: ResourceRequest, report: ResourceReport
    ) -> None:
        if (
            report.run_id != request.run_id
            or report.generation_id != request.generation_id
            or report.interval != request.interval
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

    def _persist_candidate(
        self, connector: RefreshConnector, verified: CandidateResult
    ) -> DurableResourceReceipt:
        expected = DurableResourceReceipt(
            verified.generation_id,
            connector.addresses(verified.generation_id, verified.resources),
            verified.interval,
            verified.contract_id,
            verified.transformation_id,
            verified.base_generation_id,
            verified.schema_version,
        )
        receipt = connector.persist(verified, connector.bounds)
        if receipt != expected:
            raise ArtifactError("Durable receipt mismatch")
        return receipt

    def _build_publication_generation(
        self,
        run: RefreshRun,
        connector: RefreshConnector,
        verified: CandidateResult,
        receipt: DurableResourceReceipt,
        coverage: dict[Grain, tuple[date, date]],
    ) -> ResourcePublishedGeneration:
        published_at = connector.clock.now()
        resources_by_grain = {ref.grain: ref for ref in receipt.resources}
        datasets: list[DatasetSummary] = []
        for summary in verified.summaries:
            resource = resources_by_grain[summary.grain]
            start, end = coverage[summary.grain]
            datasets.append(
                DatasetSummary(
                    grain=AnalyticalGrain(summary.grain),
                    schema_version="v1",
                    rows=summary.candidate_count,
                    start=start,
                    end=end,
                    object_key=resource.object.key,
                    sha256=resource.object.sha256,
                    byte_count=resource.object.byte_count,
                )
            )
        return ResourcePublishedGeneration(
            id=run.id,
            run_id=run.id,
            base_generation_id=run.base_generation_id,
            verification_version="v1",
            verified_at=published_at,
            datasets=tuple(datasets),
        )


class RefreshWorker:
    def __init__(
        self,
        store: RefreshStore,
        execution: RefreshExecution,
        lease: RefreshLease,
        identity: str,
        lease_seconds: int = 60,
    ) -> None:
        self.store, self.execution, self.lease = store, execution, lease
        self.identity, self.lease_seconds = identity, lease_seconds

    def tick(self) -> RefreshRun | None:
        latest = self.store.latest()
        if latest is not None and not latest.status.terminal:
            RefreshRecovery(self.store).execute(latest.id)
        owner = self.store.claim(self.identity, self.lease_seconds)
        if owner is None:
            return None
        with self.lease(owner):
            return self.execution.execute(owner)
