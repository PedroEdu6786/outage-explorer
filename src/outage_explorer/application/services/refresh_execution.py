"""Execute only committed claims using frozen inputs and verified durable resource files."""

from dataclasses import dataclass
from datetime import date

from outage_explorer.application.dto import ResourceReport
from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.candidates import CandidateResult
from outage_explorer.application.ports.publication import ResourcePublicationStore
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import (
    RefreshPipeline,
    RefreshPipelineFactory,
)
from outage_explorer.application.refresh_outcomes import quality_json, safe_failure
from outage_explorer.domain.observations import Grain
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


@dataclass
class _ExecutionState:
    """Keep failure context across pipeline cleanup and publication."""

    quality_json: str | None = None
    publication_started: bool = False


class RefreshExecution:
    def __init__(
        self,
        store: RefreshStore,
        publication: ResourcePublicationStore,
        factory: RefreshPipelineFactory,
    ) -> None:
        self.store = store
        self.publication = publication
        self.factory = factory

    def execute(self, owner: RefreshOwner) -> RefreshRun:
        """Restore, build, verify and persist a candidate before publishing it."""
        run = self._load_claimed_run(owner)
        state = _ExecutionState()
        try:
            self._start_run(run, owner)
            with self.factory(run, owner) as pipeline:
                return self._execute_pipeline(run, owner, pipeline, state)
        except (StaleRefreshOwnerError, AccessStoreError):
            raise  # Never turn loss of ownership or uncertainty into a failed outcome.
        except Exception as error:
            if state.publication_started:
                raise  # An ambiguous publication must be reconciled, never overwritten.
            return self.store.finish(
                owner, RunStatus.FAILED, state.quality_json, safe_failure(error)
            )

    def _start_run(self, run: RefreshRun, owner: RefreshOwner) -> None:
        # Check the live lease before baseline or source I/O.
        self.store.progress(owner, RefreshStage.RETRIEVING)
        if run.base_generation_id is None:
            run.configuration.validate_initial_load_start_date()

    def _execute_pipeline(
        self,
        run: RefreshRun,
        owner: RefreshOwner,
        pipeline: RefreshPipeline,
        state: _ExecutionState,
    ) -> RefreshRun:
        baseline = pipeline.baseline.restore(run)
        result = pipeline.candidate.build(run, baseline)
        report = result.report
        state.quality_json = quality_json(report)
        if report.outcome == "failed" or not result.report_written:
            return self.store.finish(
                owner, RunStatus.FAILED, state.quality_json, report.error or "report"
            )

        verified, coverage = pipeline.candidate.verify(run, report)
        state.quality_json = quality_json(report, coverage)
        if pipeline.candidate.outcome(run, report, verified) == "retain":
            return self.store.finish(owner, RunStatus.RETAINED, state.quality_json)

        return self._publish_candidate(run, owner, pipeline, verified, coverage, state)

    def _publish_candidate(
        self,
        run: RefreshRun,
        owner: RefreshOwner,
        pipeline: RefreshPipeline,
        verified: CandidateResult,
        coverage: dict[Grain, tuple[date, date]],
        state: _ExecutionState,
    ) -> RefreshRun:
        self.store.progress(owner, RefreshStage.PERSISTING, state.quality_json)
        receipt = pipeline.publication.persist(verified)
        self.store.progress(owner, RefreshStage.PUBLISHING, state.quality_json)
        generation = pipeline.publication.generation(run, verified, receipt, coverage)
        state.publication_started = True
        return self.publication.publish(owner, generation, state.quality_json)

    def _load_claimed_run(self, owner: RefreshOwner) -> RefreshRun:
        run = self.store.get_run(owner.run_id)
        if (
            run is None
            or run.status is not RunStatus.RUNNING
            or run.epoch != owner.epoch
        ):
            raise StaleRefreshOwnerError("Missing committed claim")
        return run
