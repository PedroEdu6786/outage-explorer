"""Verify candidate descriptors, file contents, quality and coverage."""

from dataclasses import replace

from outage_explorer.application.ports.artifacts import ArtifactError, ArtifactRef
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    GrainSummary,
    validate_resources,
)
from outage_explorer.domain.observations import IDENTITY_FIELDS
from outage_explorer.domain.refresh import RefreshBounds, validate_baseline_row
from outage_explorer.infrastructure.parquet.candidate.accounting import (
    candidate_outcome,
)
from outage_explorer.infrastructure.parquet.partitions import prior_days
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


def _verify_identity(candidate: CandidateResult, bounds: RefreshBounds) -> None:
    validate_resources(candidate.resources)
    if candidate.schema_version != "1" or candidate.outcome not in (
        "candidate",
        "retained_all_excluded",
    ):
        raise ArtifactError("Invalid resource candidate identity")
    if not candidate.generation_id or len(candidate.generation_id) > bounds.field_chars:
        raise ArtifactError("Invalid resource candidate identity")
    if not candidate.contract_id or not candidate.transformation_id:
        raise ArtifactError("Invalid resource candidate identity")
    if candidate.base_generation_id == candidate.generation_id:
        raise ArtifactError("Invalid resource candidate identity")
    if len(candidate.summaries) != 3 or {
        summary.grain for summary in candidate.summaries
    } != set(IDENTITY_FIELDS):
        raise ArtifactError("Invalid resource candidate identity")


def _nonnegative_counts(summary: GrainSummary) -> tuple[int, ...]:
    quality = summary.quality
    return (
        quality.received,
        quality.selected,
        quality.excluded,
        quality.duplicate,
        quality.superseded,
        summary.active_count,
        summary.candidate_count,
        summary.retained_invalid,
        summary.retained_absent,
        summary.carried_outside_interval,
        summary.observed_entities,
        summary.observed_dates,
        summary.usable_dates,
    )


def _verify_counts(
    ref: ArtifactRef, summary: GrainSummary, bounds: RefreshBounds
) -> None:
    quality = summary.quality
    if any(
        type(count) is not int or count < 0 for count in _nonnegative_counts(summary)
    ):
        raise ArtifactError("Invalid resource quality counts")
    if not 0 < quality.received <= bounds.incoming_rows:
        raise ArtifactError("Resource quality counts do not reconcile")

    dispositions = (
        quality.selected,
        quality.excluded,
        quality.duplicate,
        quality.superseded,
    )
    if quality.received != sum(dispositions):
        raise ArtifactError("Resource quality counts do not reconcile")

    retained_rows = (
        quality.selected,
        summary.retained_invalid,
        summary.retained_absent,
        summary.carried_outside_interval,
    )
    if (
        summary.candidate_count != ref.row_count
        or ref.row_count > bounds.output_rows
        or summary.candidate_count != sum(retained_rows)
    ):
        raise ArtifactError("Resource quality counts do not reconcile")

    if (
        any(type(count) is not int or count <= 0 for _, count in quality.reason_counts)
        or sum(count for _, count in quality.reason_counts) > bounds.reason_occurrences
    ):
        raise ArtifactError("Resource quality counts do not reconcile")


def _verify_file_coverage(
    store: LocalParquetStore,
    ref: ArtifactRef,
    summary: GrainSummary,
    bounds: RefreshBounds,
) -> None:
    first = last = None
    for day, rows in prior_days(
        store,
        ref,
        replace(bounds, prior_rows=bounds.output_rows),
        resource=True,
    ):
        if first is None:
            first = day
        last = day
        for row in rows:
            validate_baseline_row(row, ref.grain, bounds)
    if (summary.first_period, summary.last_period) != (first, last):
        raise ArtifactError("Resource coverage disagrees with file")


def verify_candidate_resources(
    store: LocalParquetStore, candidate: CandidateResult, bounds: RefreshBounds
) -> None:
    """Verify stored files after build's transient semantic comparison.

    Source input has been discarded, so this cannot replay candidate construction.
    """
    _verify_identity(candidate, bounds)
    summaries = {summary.grain: summary for summary in candidate.summaries}
    for ref in candidate.resources:
        store.adopt_exact(ref)
        summary = summaries[ref.grain]
        _verify_counts(ref, summary, bounds)
        _verify_file_coverage(store, ref, summary, bounds)
    if (
        candidate_outcome(candidate.summaries, candidate.base_generation_id is None)
        != candidate.outcome
    ):
        raise ArtifactError("Incorrect resource candidate outcome")
