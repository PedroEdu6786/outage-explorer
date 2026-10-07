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
    validate_resources,
)
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import (
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
        run = self.store.get_run(owner.run_id)
        if (
            run is None
            or run.status is not RunStatus.RUNNING
            or run.epoch != owner.epoch
        ):
            raise StaleRefreshOwnerError("Missing committed claim")
        report_json = None
        publishing = False
        try:
            # Check the complete owner identity and live fence before base/source I/O.
            self.store.progress(owner, RefreshStage.RETRIEVING)
            run.configuration.validate(initial=run.base_generation_id is None)
            with self.factory(run, owner) as connector:
                base = self.publication.active_generation()
                if (None if base is None else base.id) != run.base_generation_id:
                    raise StaleRefreshOwnerError("Pinned base changed")
                prior = None
                if base is not None:
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
                            Interval(
                                base_run.configuration.start, base_run.configuration.end
                            ),
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
                request = ResourceRequest(
                    Interval(run.configuration.start, run.configuration.end),
                    run.id,
                    run.id,
                    connector.bounds,
                    prior,
                )
                result = connector.candidate.run(request)
                report = result.report
                report_json = quality_json(report)
                if report.outcome == "failed" or not result.report_written:
                    return self.store.finish(
                        owner, RunStatus.FAILED, report_json, report.error or "report"
                    )
                verified = report.candidate
                if verified is None:
                    raise ArtifactError("Missing verified resource candidate")
                connector.verify(verified, connector.bounds)
                if (
                    verified.outcome
                    != (
                        "retained_all_excluded"
                        if report.outcome == "retained_all_excluded"
                        else "candidate"
                    )
                    or verified.generation_id != run.id
                    or verified.base_generation_id != run.base_generation_id
                    or verified.interval != request.interval
                    or verified.schema_version != "1"
                    or verified.contract_id != request.contract_id
                    or verified.transformation_id != request.transformation_id
                ):
                    raise ArtifactError("Verified candidate identity mismatch")
                coverage = _coverage(verified)
                report_json = quality_json(report, coverage)
                if (
                    report.run_id != run.id
                    or report.generation_id != run.id
                    or report.interval != request.interval
                ):
                    raise ArtifactError("Candidate identity mismatch")
                if report.outcome == "retained_all_excluded":
                    if (
                        base is None
                        or len(verified.summaries) != 3
                        or any(
                            item.quality.received <= 0
                            or item.quality.excluded != item.quality.received
                            for item in verified.summaries
                        )
                    ):
                        raise ArtifactError("Invalid retained outcome")
                    return self.store.finish(owner, RunStatus.RETAINED, report_json)
                if (
                    report.outcome != "candidate_verified"
                    or len(verified.summaries) != 3
                    or {item.grain for item in verified.summaries}
                    != {grain.value for grain in AnalyticalGrain}
                    or any(item.candidate_count <= 0 for item in verified.summaries)
                ):
                    raise ArtifactError("Incomplete publishable candidate")
                self.store.progress(owner, RefreshStage.PERSISTING, report_json)
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
                self.store.progress(owner, RefreshStage.PUBLISHING, report_json)
                generation = ResourcePublishedGeneration(
                    run.id,
                    run.id,
                    run.base_generation_id,
                    "v1",
                    connector.clock.now(),
                    tuple(
                        DatasetSummary(
                            AnalyticalGrain(item.grain),
                            "v1",
                            item.candidate_count,
                            *coverage[item.grain],
                            next(
                                ref.object.key
                                for ref in receipt.resources
                                if ref.grain == item.grain
                            ),
                            next(
                                ref.object.sha256
                                for ref in receipt.resources
                                if ref.grain == item.grain
                            ),
                            next(
                                ref.object.byte_count
                                for ref in receipt.resources
                                if ref.grain == item.grain
                            ),
                        )
                        for item in verified.summaries
                    ),
                )
                publishing = True
                return self.publication.publish(owner, generation, report_json)
        except (StaleRefreshOwnerError, AccessStoreError):
            raise  # Never turn loss of ownership or uncertainty into a failed outcome.
        except Exception as error:
            if publishing:
                raise  # An ambiguous publication must be reconciled, never overwritten.
            return self.store.finish(
                owner, RunStatus.FAILED, report_json, safe_failure(error)
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
