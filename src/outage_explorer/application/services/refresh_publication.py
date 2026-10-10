"""Persist exact refresh resources and prepare metadata for atomic publication."""

from collections.abc import Callable
from datetime import date

from outage_explorer.application.ports.artifacts import ArtifactError, ArtifactRef
from outage_explorer.application.ports.candidates import CandidateResult
from outage_explorer.application.ports.clock import Clock
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.publication import (
    DatasetSummary,
    RefreshRun,
    ResourcePublishedGeneration,
)
from outage_explorer.domain.refresh import RefreshBounds


class PrepareRefreshPublication:
    def __init__(
        self,
        addresses: Callable[[str, tuple[ArtifactRef, ...]], tuple[ArtifactRef, ...]],
        persist: Callable[[CandidateResult, RefreshBounds], DurableResourceReceipt],
        bounds: RefreshBounds,
        clock: Clock,
    ) -> None:
        self._addresses = addresses
        self._persist = persist
        self._bounds = bounds
        self._clock = clock

    def persist(self, verified: CandidateResult) -> DurableResourceReceipt:
        expected = DurableResourceReceipt(
            verified.generation_id,
            self._addresses(verified.generation_id, verified.resources),
            verified.interval,
            verified.contract_id,
            verified.transformation_id,
            verified.base_generation_id,
            verified.schema_version,
        )
        receipt = self._persist(verified, self._bounds)
        if receipt != expected:
            raise ArtifactError("Durable receipt mismatch")
        return receipt

    def generation(
        self,
        run: RefreshRun,
        verified: CandidateResult,
        receipt: DurableResourceReceipt,
        coverage: dict[Grain, tuple[date, date]],
    ) -> ResourcePublishedGeneration:
        published_at = self._clock.now()
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
