"""Local bounded Parquet candidates; no activation, retrieval or publication."""

import logging
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date
from itertools import chain, zip_longest

from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.application.ports.candidates import (
    CandidateResult,
    GrainSummary,
    ResourceBaseline,
    TransientInput,
    validate_resources,
)
from outage_explorer.domain.observations import IDENTITY_FIELDS, Grain, Reason
from outage_explorer.domain.refresh import (
    EmptySourceError,
    IncomingRow,
    ModeledPartition,
    Quality,
    RefreshBounds,
    RefreshInputError,
    merge_partition,
    model_partition,
    validate_baseline_row,
)
from outage_explorer.infrastructure.parquet.partitions import (
    DayMerge,
    day_walk,
    prior_days,
    row_day,
)
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

_LOG = logging.getLogger("outage_explorer.connector.parquet")


@dataclass
class _Accounting:
    grain: Grain
    counts: Counter[str] = field(default_factory=Counter)
    reasons: Counter[Reason] = field(default_factory=Counter)
    identities: set[tuple[str, ...]] = field(default_factory=set)
    observed_dates: set[date] = field(default_factory=set)
    usable_dates: set[date] = field(default_factory=set)
    first_period: date | None = None
    last_period: date | None = None

    def add(self, day: DayMerge, bounds: RefreshBounds) -> None:
        merged = day.merged
        quality = merged.incoming.quality
        for name in ("received", "selected", "excluded", "duplicate", "superseded"):
            self.counts[name] += getattr(quality, name)
        self.reasons.update(dict(quality.reason_counts))
        self.counts["active"] += merged.active_count
        self.counts["candidate"] += merged.candidate_count
        self.counts["invalid"] += len(merged.retained_invalid_keys)
        self.counts["absent"] += len(merged.absent_prior_rows)
        self.counts["outside"] += len(merged.carried_outside_keys)
        if merged.rows and day.day is not None:
            # Days arrive ascending, so the first and last populated days bound
            # the dataset's period coverage.
            self.first_period = self.first_period or day.day
            self.last_period = day.day
        self.identities.update(merged.incoming.observed_identities)
        self.observed_dates.update(merged.incoming.observed_dates)
        self.usable_dates.update(row.observation.day for row in merged.incoming.rows)
        # Per-dataset cumulative bounds; the domain checks one day group at a time.
        if self.counts["received"] > bounds.incoming_rows:
            raise ArtifactLimitError("Incoming dataset row bound exceeded")
        if self.counts["candidate"] > bounds.output_rows:
            raise ArtifactLimitError("Output dataset row bound exceeded")
        # Exact incoming coverage cardinalities are bounded separately from the
        # number of historical rows scanned, reusing explicit caller limits.
        if len(self.identities) > bounds.output_rows:
            raise ArtifactLimitError("Observed identity cardinality bound exceeded")
        if sum(self.reasons.values()) > bounds.reason_occurrences:
            raise ArtifactLimitError("Route reason occurrence bound exceeded")

    def summary(self) -> GrainSummary:
        c = self.counts
        if c["received"] == 0:
            raise EmptySourceError("Required route received no observations")
        quality = Quality(
            c["received"],
            c["selected"],
            c["excluded"],
            c["duplicate"],
            c["superseded"],
            tuple(
                sorted(
                    self.reasons.items(), key=lambda pair: (pair[0].field, pair[0].code)
                )
            ),
        )
        if quality.received != sum(
            (quality.selected, quality.excluded, quality.duplicate, quality.superseded)
        ):
            raise ArtifactError("Disposition counts do not reconcile")
        if c["candidate"] != c["selected"] + c["invalid"] + c["absent"] + c["outside"]:
            raise ArtifactError("Merge counts do not reconcile")
        return GrainSummary(
            self.grain,
            quality,
            c["active"],
            c["candidate"],
            c["invalid"],
            c["absent"],
            c["outside"],
            len(self.identities),
            len(self.observed_dates),
            len(self.usable_dates),
            self.first_period,
            self.last_period,
        )


def _outcome(summaries: tuple[GrainSummary, ...], initial: bool) -> str:
    if initial and any(summary.quality.selected == 0 for summary in summaries):
        raise RefreshInputError(
            "Initial load requires usable output in all three grains"
        )
    if not initial and any(summary.active_count == 0 for summary in summaries):
        raise RefreshInputError("Prior generation must contain all three grains")
    if all(summary.quality.selected == 0 for summary in summaries):
        return "retained_all_excluded"
    return "candidate"


def _grain_ref(refs: tuple[ArtifactRef, ...], grain: Grain) -> ArtifactRef | None:
    """The single dataset file of a grain; manifest validation bounds it to one."""
    return next((ref for ref in refs if ref.grain == grain), None)


class ParquetResourceBuilder:
    """New three-file local pipeline, explicitly injected until phase-4 cutover."""

    def __init__(self, store: LocalParquetStore) -> None:
        self.store = store

    def verify_baseline(self, prior: ResourceBaseline, bounds: RefreshBounds) -> None:
        prior.__post_init__()
        for ref in prior.resources:
            self.store.adopt_exact(ref)
            for _, rows in prior_days(self.store, ref, bounds, resource=True):
                for row in rows:
                    validate_baseline_row(row, ref.grain, bounds)

    def _inputs_resources(
        self, inputs: Iterable[TransientInput], bounds: RefreshBounds
    ) -> tuple[TransientInput, ...]:
        collected: dict[Grain, TransientInput] = {}
        size = 0
        identity: tuple[str, str, str] | None = None
        for item in inputs:
            self.store.check()
            if item.grain not in IDENTITY_FIELDS or item.grain in collected:
                raise RefreshInputError("Expected one transient input per grain")
            if not item.rows:
                raise EmptySourceError("Required route received no observations")
            if len(item.rows) > bounds.incoming_rows:
                raise ArtifactLimitError("Incoming dataset row bound exceeded")
            if type(item.byte_count) is not int or item.byte_count <= 0:
                raise ArtifactError("Invalid transient input byte count")
            size += item.byte_count
            if size > self.store.bounds.total_bytes:
                raise ArtifactLimitError(
                    "Aggregate transient input byte bound exceeded"
                )
            if (
                item.interval.end - item.interval.start
            ).days + 1 > bounds.interval_days:
                raise ArtifactLimitError("Requested interval bound exceeded")
            current = item.run_id, item.contract_id, item.transformation_id
            if identity is not None and current != identity:
                raise RefreshInputError(
                    "Mixed run, contract or transformation identities"
                )
            identity = current
            if any(not value or len(value) > bounds.field_chars for value in current):
                raise RefreshInputError("Invalid transient version identity")
            collected[item.grain] = item
        if set(collected) != set(IDENTITY_FIELDS):
            raise RefreshInputError("All three grains are required")
        if len({item.interval for item in collected.values()}) != 1:
            raise RefreshInputError("Route intervals differ")
        return tuple(collected[grain] for grain in IDENTITY_FIELDS)

    def _stage_resource(
        self, item: TransientInput
    ) -> dict[date | None, tuple[IncomingRow, ...]]:
        staged: dict[date | None, list[IncomingRow]] = {}
        retrieval: str | None = None
        page_rows: set[tuple[int, int]] = set()
        for position, row in enumerate(item.rows):
            self.store.check()
            origin = row.origin
            current = origin.page_index, origin.row_index
            if (
                origin.source_position != position
                or current in page_rows
                or origin.grain != item.grain
                or origin.run_id != item.run_id
                or origin.contract_id != item.contract_id
                or origin.transformation_id != item.transformation_id
                or (retrieval is not None and retrieval != origin.retrieval_id)
            ):
                raise ArtifactError("Transient source identity/order mismatch")
            retrieval = origin.retrieval_id
            page_rows.add(current)
            day = row_day(row)
            if day is not None and not item.interval.contains(day):
                raise RefreshInputError("Source observation outside requested interval")
            staged.setdefault(day, []).append(row)
        return {day: tuple(rows) for day, rows in staged.items()}

    def _resource_walk(
        self,
        item: TransientInput,
        staged: dict[date | None, tuple[IncomingRow, ...]],
        prior: ArtifactRef | None,
        bounds: RefreshBounds,
    ) -> Iterator[DayMerge]:
        for position, (day, old) in enumerate(
            day_walk(
                item.interval, prior_days(self.store, prior, bounds, resource=True)
            )
        ):
            self.store.check()
            if position % 14 == 0 or day == item.interval.end:
                _LOG.info(
                    "resource_merge_progress grain=%s partition=%s", item.grain, day
                )
            rows = staged.get(day, ())
            incoming = (
                model_partition(item.grain, item.interval, rows, bounds)
                if rows
                else ModeledPartition(
                    item.grain,
                    item.interval,
                    (),
                    (),
                    frozenset(),
                    frozenset(),
                    frozenset(),
                    Quality(0, 0, 0, 0, 0, ()),
                )
            )
            yield DayMerge(day, merge_partition(incoming, old, bounds), old)

    def build_resources(
        self,
        generation_id: str,
        inputs: Iterable[TransientInput],
        bounds: RefreshBounds,
        prior: ResourceBaseline | None = None,
    ) -> CandidateResult:
        if not generation_id or len(generation_id) > bounds.field_chars:
            raise RefreshInputError("Invalid generation identity")
        collected = self._inputs_resources(inputs, bounds)
        versions = collected[0].contract_id, collected[0].transformation_id
        if prior is not None:
            if prior.generation_id == generation_id or versions != (
                prior.contract_id,
                prior.transformation_id,
            ):
                raise RefreshInputError("Incompatible resource baseline")
            self.verify_baseline(prior, bounds)
        refs: list[ArtifactRef] = []
        summaries: list[GrainSummary] = []
        for item in collected:
            _LOG.info("resource_build_started grain=%s", item.grain)
            staged = self._stage_resource(item)
            base = None if prior is None else _grain_ref(prior.resources, item.grain)
            account = _Accounting(item.grain)

            # Complete accounting/eligibility before committing this grain. Empty
            # initial output is an eligibility failure, never a silent exclusion.
            stream = self._resource_records(item, staged, base, bounds, account)
            first = next(stream, None)
            if first is None:
                raise RefreshInputError(
                    "Initial load requires usable output in all three grains"
                )
            ref = self.store.write_file("resource", item.grain, chain((first,), stream))
            summary = account.summary()
            replay = _Accounting(item.grain)

            expected = self._resource_records(item, staged, base, bounds, replay)
            for actual, wanted in zip_longest(self.store.records(ref), expected):
                if actual != wanted:
                    raise ArtifactError("Resource values disagree with transient merge")
            if replay.summary() != summary or ref.row_count != summary.candidate_count:
                raise ArtifactError("Resource quality/coverage does not reconcile")
            refs.append(ref)
            summaries.append(summary)
            _LOG.info("resource_verify_complete grain=%s", item.grain)
        outcome = _outcome(tuple(summaries), prior is None)
        candidate = CandidateResult(
            generation_id,
            None if prior is None else prior.generation_id,
            collected[0].interval,
            tuple(refs),
            tuple(summaries),
            "candidate" if outcome == "candidate" else "retained_all_excluded",
            *versions,
        )
        self.verify_resources(candidate, bounds)
        return candidate

    def _resource_records(
        self,
        item: TransientInput,
        staged: dict[date | None, tuple[IncomingRow, ...]],
        base: ArtifactRef | None,
        bounds: RefreshBounds,
        account: _Accounting,
    ) -> Iterator[dict[str, object]]:
        for part in self._resource_walk(item, staged, base, bounds):
            account.add(part, bounds)
            for row in part.merged.rows:
                yield modeled_record(row)

    def verify_resources(
        self, candidate: CandidateResult, bounds: RefreshBounds
    ) -> None:
        """Verify descriptors/files after build's transient semantic comparison.

        This does not replay discarded source input and cannot establish that an
        arbitrary caller-created descriptor passed semantic candidate construction.
        """
        validate_resources(candidate.resources)
        if (
            candidate.schema_version != "1"
            or not candidate.generation_id
            or len(candidate.generation_id) > bounds.field_chars
            or not candidate.contract_id
            or not candidate.transformation_id
            or candidate.base_generation_id == candidate.generation_id
            or candidate.outcome not in ("candidate", "retained_all_excluded")
            or len(candidate.summaries) != 3
            or {s.grain for s in candidate.summaries} != set(IDENTITY_FIELDS)
        ):
            raise ArtifactError("Invalid resource candidate identity")
        for ref in candidate.resources:
            self.store.adopt_exact(ref)
            summary = next(s for s in candidate.summaries if s.grain == ref.grain)
            quality = summary.quality
            counts = (
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
            if any(type(n) is not int or n < 0 for n in counts):
                raise ArtifactError("Invalid resource quality counts")
            if (
                quality.received <= 0
                or quality.received > bounds.incoming_rows
                or quality.received
                != sum(
                    (
                        quality.selected,
                        quality.excluded,
                        quality.duplicate,
                        quality.superseded,
                    )
                )
                or summary.candidate_count != ref.row_count
                or ref.row_count > bounds.output_rows
                or summary.candidate_count
                != sum(
                    (
                        quality.selected,
                        summary.retained_invalid,
                        summary.retained_absent,
                        summary.carried_outside_interval,
                    )
                )
                or any(type(n) is not int or n <= 0 for _, n in quality.reason_counts)
                or sum(n for _, n in quality.reason_counts) > bounds.reason_occurrences
            ):
                raise ArtifactError("Resource quality counts do not reconcile")
            first = last = None
            for day, rows in prior_days(
                self.store,
                ref,
                replace(bounds, prior_rows=bounds.output_rows),
                resource=True,
            ):
                first = first or day
                last = day
                for row in rows:
                    validate_baseline_row(row, ref.grain, bounds)
            if (summary.first_period, summary.last_period) != (first, last):
                raise ArtifactError("Resource coverage disagrees with file")
        if (
            _outcome(candidate.summaries, candidate.base_generation_id is None)
            != candidate.outcome
        ):
            raise ArtifactError("Incorrect resource candidate outcome")
