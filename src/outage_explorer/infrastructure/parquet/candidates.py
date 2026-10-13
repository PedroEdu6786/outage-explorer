"""Local bounded Parquet candidates; no activation, retrieval or publication."""

from collections.abc import Iterable

from outage_explorer.application.ports.artifacts import ArtifactRef
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    ResourceBaseline,
    TransientInput,
)
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import (
    RefreshBounds,
    RefreshInputError,
    validate_baseline_row,
)
from outage_explorer.infrastructure.parquet.candidate.accounting import (
    candidate_outcome,
)
from outage_explorer.infrastructure.parquet.candidate.grain import ParquetGrainBuilder
from outage_explorer.infrastructure.parquet.candidate.inputs import (
    CandidateInputValidator,
)
from outage_explorer.infrastructure.parquet.candidate.verification import (
    verify_candidate_resources,
)
from outage_explorer.infrastructure.parquet.partitions import prior_days
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


def _grain_ref(refs: tuple[ArtifactRef, ...], grain: Grain) -> ArtifactRef | None:
    """Find this grain's file in the verified baseline."""
    return next((ref for ref in refs if ref.grain == grain), None)


class ParquetResourceBuilder:
    """Build and verify the three local resource files for one generation."""

    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store
        self._inputs = CandidateInputValidator(store)
        self._grain = ParquetGrainBuilder(store)

    def verify_baseline(self, prior: ResourceBaseline, bounds: RefreshBounds) -> None:
        prior.__post_init__()
        for ref in prior.resources:
            self.store.adopt_exact(ref)
            for _, rows in prior_days(self.store, ref, bounds, resource=True):
                for row in rows:
                    validate_baseline_row(row, ref.grain, bounds)

    def build_resources(
        self,
        generation_id: str,
        inputs: Iterable[TransientInput],
        bounds: RefreshBounds,
        prior: ResourceBaseline | None = None,
    ) -> CandidateResult:
        if not generation_id or len(generation_id) > bounds.field_chars:
            raise RefreshInputError("Invalid generation identity")
        collected = self._inputs.validate(inputs, bounds)
        versions = collected[0].contract_id, collected[0].transformation_id
        if prior is not None:
            if prior.generation_id == generation_id or versions != (
                prior.contract_id,
                prior.transformation_id,
            ):
                raise RefreshInputError("Incompatible resource baseline")
            self.verify_baseline(prior, bounds)
        built = tuple(
            self._grain.build(
                item,
                bounds,
                None if prior is None else _grain_ref(prior.resources, item.grain),
            )
            for item in collected
        )
        refs = tuple(ref for ref, _ in built)
        summaries = tuple(summary for _, summary in built)
        outcome = candidate_outcome(summaries, prior is None)
        candidate = CandidateResult(
            generation_id,
            None if prior is None else prior.generation_id,
            collected[0].interval,
            refs,
            summaries,
            "candidate" if outcome == "candidate" else "retained_all_excluded",
            *versions,
        )
        self.verify_resources(candidate, bounds)
        return candidate

    def verify_resources(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> None:
        verify_candidate_resources(self.store, candidate, bounds)
