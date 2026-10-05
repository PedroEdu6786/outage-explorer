"""Bounded day groups and sorted history scans for local candidate construction."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from outage_explorer.application.ports.artifacts import (
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.application.ports.candidates import EvidenceBundle
from outage_explorer.domain.observations import Grain, parse_day
from outage_explorer.domain.refresh import (
    IncomingRow,
    Interval,
    MergedPartition,
    ModeledPartition,
    ModeledRow,
    Quality,
    RefreshBounds,
    RefreshInputError,
    merge_partition,
    model_partition,
)
from outage_explorer.infrastructure.parquet.evidence import replay_evidence
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    origin_record,
    raw_from_record,
    raw_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

PartitionIndex = dict[date | None, tuple[ArtifactRef, ...]]


def row_day(row: IncomingRow) -> date | None:
    value = row.value
    if not isinstance(value, Mapping):
        return None
    period = value.get("period")
    return parse_day(period) if isinstance(period, str) else None


def stage_dates(store: LocalParquetStore, bundle: EvidenceBundle) -> PartitionIndex:
    """Spool bounded batches, closing files between writes; preserve source order."""
    index: dict[date | None, list[ArtifactRef]] = {}
    buffered: dict[date | None, list[dict[str, object]]] = {}
    count = 0

    def flush() -> None:
        for day, records in buffered.items():
            refs = store.write("raw", bundle.grain, day, records)
            index.setdefault(day, []).extend(refs)
            if sum(len(value) for value in index.values()) > store.bounds.objects:
                raise ArtifactLimitError("Date partition object bound exceeded")
        buffered.clear()

    for row in replay_evidence(store, bundle):
        day = row_day(row)
        if day is not None and not bundle.interval.contains(day):
            raise RefreshInputError("Source observation outside requested interval")
        buffered.setdefault(day, []).append(raw_record(row, bundle.interval))
        count += 1
        if count == store.bounds.batch_rows:
            flush()
            count = 0
    flush()
    return {day: tuple(refs) for day, refs in index.items()}


def index_modeled(refs: tuple[ArtifactRef, ...], grain: Grain) -> PartitionIndex:
    result: dict[date | None, list[ArtifactRef]] = {}
    for ref in refs:
        if ref.grain != grain:
            continue
        if ref.kind != "modeled" or ref.partition is None:
            raise RefreshInputError("Modeled reference needs a date partition")
        result.setdefault(ref.partition, []).append(ref)
    return {day: tuple(values) for day, values in result.items()}


def day_sequence(interval: Interval, prior: PartitionIndex) -> Iterator[date | None]:
    # Metadata only, never history rows; interval length is checked before this.
    dates = {day for day in prior if day is not None}
    day = interval.start
    while day <= interval.end:
        dates.add(day)
        if day == date.max:
            break
        day += timedelta(days=1)
    yield None  # malformed dates still get dispositions and quality counts
    yield from sorted(dates)


def incoming_day(
    store: LocalParquetStore,
    bundle: EvidenceBundle,
    day: date | None,
    staged: PartitionIndex | None,
) -> Iterator[IncomingRow]:
    if staged is not None:
        for ref in staged.get(day, ()):
            for record in store.records(ref):
                yield raw_from_record(record)
        return
    # Unindexed fallback for callers without derived staging; candidate verification
    # rebuilds bounded day indexes from fresh replay instead of rescanning per day.
    for row in replay_evidence(store, bundle):
        actual_day = row_day(row)
        if actual_day is not None and not bundle.interval.contains(actual_day):
            raise RefreshInputError("Source observation outside requested interval")
        if actual_day == day:
            yield row


def prior_day(
    store: LocalParquetStore, refs: tuple[ArtifactRef, ...], bounds: RefreshBounds
) -> tuple[ModeledRow, ...]:
    rows: list[ModeledRow] = []
    previous = None
    for ref in refs:
        for record in store.records(ref):
            row = modeled_from_record(record, ref.grain)
            if row.observation.day != ref.partition:
                raise RefreshInputError("Modeled row does not match partition")
            if previous is not None and row.key <= previous:
                raise RefreshInputError(
                    "Duplicate or unsorted modeled keys across files"
                )
            previous = row.key
            if len(rows) >= bounds.prior_rows:
                raise ArtifactLimitError("Prior day row bound exceeded")
            rows.append(row)
    return tuple(rows)


@dataclass(frozen=True)
class DayMerge:
    day: date | None
    merged: MergedPartition
    old: tuple[ModeledRow, ...]

    def ledger(self) -> Iterator[dict[str, object]]:
        previous = {row.key: row for row in self.old}
        incoming = self.merged.incoming.usable_keys
        exclusions: dict[tuple[date, tuple[str, ...]], list[int]] = {}
        for decision in self.merged.incoming.decisions:
            assessment = decision.disposition.assessment
            if (
                decision.disposition.status == "excluded"
                and assessment.day is not None
                and assessment.identity is not None
            ):
                exclusions.setdefault((assessment.day, assessment.identity), []).append(
                    assessment.position
                )
        for row in self.merged.rows:
            old = previous.get(row.key)
            if row.key in incoming:
                action = "new" if old is None else "replace"
            elif row.key in self.merged.carried_outside_keys:
                action = "carry_outside_interval"
            elif row.key in self.merged.retained_invalid_keys:
                action = "retain_invalid"
            else:
                action = "retain_absent"
            yield {
                "period": row.observation.day,
                "identity": list(row.observation.identity),
                "action": action,
                "origin": origin_record(row.origin),
                "old_origin": None if old is None else origin_record(old.origin),
                "exclusion_positions": exclusions.get(row.key, []),
            }


def merge_day(
    store: LocalParquetStore,
    bundle: EvidenceBundle,
    day: date | None,
    prior: PartitionIndex,
    bounds: RefreshBounds,
    staged: PartitionIndex | None = None,
) -> DayMerge:
    rows = incoming_day(store, bundle, day, staged)
    first = next(rows, None)
    if first is not None:

        def combined() -> Iterator[IncomingRow]:
            yield first
            yield from rows

        modeled = model_partition(bundle.grain, bundle.interval, combined(), bounds)
    else:
        modeled = ModeledPartition(
            bundle.grain,
            bundle.interval,
            (),
            (),
            frozenset(),
            frozenset(),
            frozenset(),
            Quality(0, 0, 0, 0, 0, ()),
        )
    old = prior_day(store, prior.get(day, ()), bounds)
    return DayMerge(day, merge_partition(modeled, old, bounds), old)
