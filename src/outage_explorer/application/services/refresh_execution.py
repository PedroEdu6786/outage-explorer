"""Execute only committed claims using frozen inputs and verified durable resource files."""

from outage_explorer.application.dto import ResourceReport
from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import (
    RefreshLease,
    RefreshPipelineFactory,
)
from outage_explorer.application.refresh_outcomes import quality_json, safe_failure
from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.domain.publication import (
    RefreshOwner,
    RefreshRun,
    RefreshStage,
    RunStatus,
)


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


class RefreshExecution:
    def __init__(
        self,
        store: RefreshStore,
        publication: ResourcePublicationStore,
        factory: RefreshPipelineFactory,
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
            with self.factory(run, owner) as pipeline:
                baseline = pipeline.baseline.restore(run)
                result = pipeline.candidate.build(run, baseline)
                report = result.report
                report_json = quality_json(report)
                if report.outcome == "failed" or not result.report_written:
                    return self.store.finish(
                        owner, RunStatus.FAILED, report_json, report.error or "report"
                    )

                verified, coverage = pipeline.candidate.verify(run, report)
                report_json = quality_json(report, coverage)
                outcome = pipeline.candidate.outcome(run, report, verified)
                if outcome == "retain":
                    return self.store.finish(owner, RunStatus.RETAINED, report_json)

                self.store.progress(owner, RefreshStage.PERSISTING, report_json)
                receipt = pipeline.publication.persist(verified)

                self.store.progress(owner, RefreshStage.PUBLISHING, report_json)
                generation = pipeline.publication.generation(
                    run, verified, receipt, coverage
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


class RefreshWorker:
    def __init__(
        self,
        store: RefreshStore,
        execution: RefreshExecution,
        lease: RefreshLease,
        identity: str,
        lease_seconds: int = 60,
    ) -> None:
        self.store = store
        self.execution = execution
        self.lease = lease
        self.identity = identity
        self.lease_seconds = lease_seconds

    def tick(self) -> RefreshRun | None:
        """Recover unfinished work, then claim and execute at most one queued run."""
        self._recover_unfinished_run()

        claimed_owner = self.store.claim(self.identity, self.lease_seconds)
        if claimed_owner is None:
            return None

        return self._execute_claimed_run(claimed_owner)

    def _recover_unfinished_run(self) -> None:
        latest_run = self.store.latest()
        if latest_run is None:
            return
        if latest_run.status.terminal:
            return

        RefreshRecovery(self.store).execute(latest_run.id)

    def _execute_claimed_run(self, owner: RefreshOwner) -> RefreshRun:
        """Keep renewing ownership until execution returns or raises an error."""
        with self.lease(owner):
            return self.execution.execute(owner)
