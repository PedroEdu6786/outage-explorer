"""Execute only committed claims using frozen inputs and verified durable graphs."""

from outage_explorer.application.dto import ConnectorReport, ConnectorRequest
from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.artifacts import ArtifactError
from outage_explorer.application.ports.publication import PublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import (
    RefreshConnectorFactory,
    RefreshLease,
)
from outage_explorer.application.refresh_outcomes import quality_json, safe_failure
from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import (
    DatasetSummary,
    PublishedGeneration,
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.domain.refresh import Interval


class RefreshReports:
    """Connector progress adapter; durable status contains only safe bounded counts."""

    def __init__(self, store: RefreshStore, owner: RefreshOwner) -> None:
        self.store, self.owner = store, owner

    def progress(self, report: ConnectorReport) -> None:
        stage = {
            "prior": RefreshStage.RETRIEVING,
            "retrieval": RefreshStage.RETRIEVING,
            "modeling": RefreshStage.MODELING,
            "verification": RefreshStage.VERIFYING,
            "complete": RefreshStage.VERIFYING,
        }[report.stage]
        self.store.progress(self.owner, stage, quality_json(report))

    def finish(self, report: ConnectorReport) -> None:
        self.store.progress(self.owner, RefreshStage.VERIFYING, quality_json(report))


class RefreshExecution:
    def __init__(
        self,
        store: RefreshStore,
        publication: PublicationStore,
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
                    prior = connector.reference(base.manifest_key, base.manifest_digest)
                    pinned = connector.restore(prior, connector.bounds)
                    if pinned.generation_id != base.id or pinned.outcome != "candidate":
                        raise ArtifactError("Pinned base identity mismatch")
                    restored = connector.graph.graph(prior, connector.bounds)
                    if not restored or restored[-1] != prior:
                        raise ArtifactError("Invalid restored graph")
                request = ConnectorRequest(
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
                reference = report.manifest
                if reference is None:
                    raise ArtifactError("Missing verified manifest")
                # Full graph replay, not a caller-supplied candidate or arbitrary receipt.
                connector.graph.graph(reference, connector.bounds)
                verified = connector.reopen(reference, connector.bounds)
                if (
                    verified.generation_id != run.id
                    or verified.base_generation_id != run.base_generation_id
                    or verified.interval != request.interval
                    or verified.summaries != report.models
                    or verified.base_manifest_object != prior
                    or verified.schema_version != "1"
                    or verified.contract_id != request.contract_id
                    or verified.transformation_id != request.transformation_id
                ):
                    raise ArtifactError("Verified candidate identity mismatch")
                coverage = {}
                for grain in {item.grain for item in verified.modeled}:
                    days = [
                        ref.partition
                        for ref in verified.modeled
                        if ref.grain == grain and ref.partition is not None
                    ]
                    if days:
                        coverage[grain] = (min(days), max(days))
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
                        or len(report.models) != 3
                        or any(
                            item.quality.received <= 0
                            or item.quality.excluded != item.quality.received
                            for item in report.models
                        )
                    ):
                        raise ArtifactError("Invalid retained outcome")
                    return self.store.finish(owner, RunStatus.RETAINED, report_json)
                if (
                    report.outcome != "candidate_verified"
                    or len(report.models) != 3
                    or {item.grain for item in report.models}
                    != {grain.value for grain in AnalyticalGrain}
                    or any(item.candidate_count <= 0 for item in report.models)
                ):
                    raise ArtifactError("Incomplete publishable candidate")
                self.store.progress(owner, RefreshStage.PERSISTING, report_json)
                receipt = connector.persist(reference, connector.bounds)
                if receipt.manifest != reference:
                    raise ArtifactError("Durable receipt mismatch")
                self.store.progress(owner, RefreshStage.PUBLISHING, report_json)
                generation = PublishedGeneration(
                    run.id,
                    run.id,
                    run.base_generation_id,
                    reference.key,
                    reference.sha256,
                    "v1",
                    connector.clock.now(),
                    tuple(
                        DatasetSummary(
                            AnalyticalGrain(item.grain),
                            "v1",
                            item.candidate_count,
                            min(
                                ref.partition
                                for ref in verified.modeled
                                if ref.grain == item.grain and ref.partition is not None
                            ),
                            max(
                                ref.partition
                                for ref in verified.modeled
                                if ref.grain == item.grain and ref.partition is not None
                            ),
                        )
                        for item in report.models
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
