"""Per-grain candidate quality accounting and publication eligibility."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import GrainSummary
from outage_explorer.domain.observations import Grain, Reason
from outage_explorer.domain.refresh import (
    EmptySourceError,
    Quality,
    RefreshBounds,
    RefreshInputError,
    refresh_facts_from_counts,
)
from outage_explorer.infrastructure.parquet.partitions import DayMerge


@dataclass
class _CandidateCounts:
    received: int = 0
    selected: int = 0
    excluded: int = 0
    duplicate: int = 0
    superseded: int = 0
    active: int = 0
    candidate: int = 0
    retained_invalid: int = 0
    retained_absent: int = 0
    carried_outside: int = 0

    def add(self, day: DayMerge) -> None:
        incoming = day.merged.incoming.quality
        self.received += incoming.received
        self.selected += incoming.selected
        self.excluded += incoming.excluded
        self.duplicate += incoming.duplicate
        self.superseded += incoming.superseded

        merged = day.merged
        self.active += merged.active_count
        self.candidate += merged.candidate_count
        self.retained_invalid += len(merged.retained_invalid_keys)
        self.retained_absent += len(merged.absent_prior_rows)
        self.carried_outside += len(merged.carried_outside_keys)

    def quality(self, reasons: Counter[Reason]) -> Quality:
        quality = Quality(
            self.received,
            self.selected,
            self.excluded,
            self.duplicate,
            self.superseded,
            tuple(
                sorted(reasons.items(), key=lambda pair: (pair[0].field, pair[0].code))
            ),
        )
        if quality.received != sum(
            (quality.selected, quality.excluded, quality.duplicate, quality.superseded)
        ):
            raise ArtifactError("Disposition counts do not reconcile")
        if self.candidate != (
            self.selected
            + self.retained_invalid
            + self.retained_absent
            + self.carried_outside
        ):
            raise ArtifactError("Merge counts do not reconcile")
        return quality


@dataclass
class CandidateAccounting:
    grain: Grain
    counts: _CandidateCounts = field(default_factory=_CandidateCounts)
    reasons: Counter[Reason] = field(default_factory=Counter)
    identities: set[tuple[str, ...]] = field(default_factory=set)
    observed_dates: set[date] = field(default_factory=set)
    usable_dates: set[date] = field(default_factory=set)
    first_period: date | None = None
    last_period: date | None = None

    def add(self, day: DayMerge, bounds: RefreshBounds) -> None:
        self.counts.add(day)
        self.reasons.update(dict(day.merged.incoming.quality.reason_counts))
        self._add_coverage(day)
        self._check_bounds(bounds)

    def _add_coverage(self, day: DayMerge) -> None:
        if day.merged.rows and day.day is not None:
            # Days arrive ascending, so the first and last populated days bound
            # the dataset's period coverage.
            self.first_period = self.first_period or day.day
            self.last_period = day.day
        incoming = day.merged.incoming
        self.identities.update(incoming.observed_identities)
        self.observed_dates.update(incoming.observed_dates)
        self.usable_dates.update(row.observation.day for row in incoming.rows)

    def _check_bounds(self, bounds: RefreshBounds) -> None:
        # Per-dataset cumulative bounds; the domain checks one day group at a time.
        if self.counts.received > bounds.incoming_rows:
            raise ArtifactLimitError("Incoming dataset row bound exceeded")
        if self.counts.candidate > bounds.output_rows:
            raise ArtifactLimitError("Output dataset row bound exceeded")
        # Exact incoming coverage cardinalities are bounded separately from the
        # number of historical rows scanned, reusing explicit caller limits.
        if len(self.identities) > bounds.output_rows:
            raise ArtifactLimitError("Observed identity cardinality bound exceeded")
        if sum(self.reasons.values()) > bounds.reason_occurrences:
            raise ArtifactLimitError("Route reason occurrence bound exceeded")

    def summary(self) -> GrainSummary:
        if self.counts.received == 0:
            raise EmptySourceError("Required route received no observations")
        return GrainSummary(
            grain=self.grain,
            quality=self.counts.quality(self.reasons),
            active_count=self.counts.active,
            candidate_count=self.counts.candidate,
            retained_invalid=self.counts.retained_invalid,
            retained_absent=self.counts.retained_absent,
            carried_outside_interval=self.counts.carried_outside,
            observed_entities=len(self.identities),
            observed_dates=len(self.observed_dates),
            usable_dates=len(self.usable_dates),
            first_period=self.first_period,
            last_period=self.last_period,
        )


def candidate_outcome(summaries: tuple[GrainSummary, ...], initial: bool) -> str:
    facts = refresh_facts_from_counts(
        {summary.grain: summary.quality for summary in summaries},
        {summary.grain: summary.active_count for summary in summaries},
    )
    if not initial and facts.mode != "refresh":
        raise RefreshInputError("Prior generation must contain all three grains")
    if facts.retain_active_without_publication:
        return "retained_all_excluded"
    if not facts.transformation_eligible:
        raise RefreshInputError(
            "Initial load requires usable output in all three grains"
        )
    return "candidate"
