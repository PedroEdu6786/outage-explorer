"""Bounded day groups and sorted history scans for local candidate construction."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from outage_explorer.application.ports.artifacts import (
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.application.ports.candidates import EvidenceBundle
from outage_explorer.domain.observations import parse_day
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

StagedDays = dict[date | None, tuple[ArtifactRef, ...]]


def row_day(row: IncomingRow) -> date | None:
    value = row.value
    if not isinstance(value, Mapping):
        return None
    period = value.get("period")
    return parse_day(period) if isinstance(period, str) else None


def stage_dates(store: LocalParquetStore, bundle: EvidenceBundle) -> StagedDays:
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


def incoming_day(
    store: LocalParquetStore, day: date | None, staged: StagedDays
) -> Iterator[IncomingRow]:
    for ref in staged.get(day, ()):
        for record in store.records(ref):
            yield raw_from_record(record)


def prior_days(
    store: LocalParquetStore,
    ref: ArtifactRef | None,
    bounds: RefreshBounds,
    *,
    resource: bool = False,
) -> Iterator[tuple[date, tuple[ModeledRow, ...]]]:
    """Stream the prior single modeled file as ascending day groups.

    Keys must be strictly increasing, which also rejects duplicates. Only one day
    group is held; cumulative rows are bounded per dataset by ``prior_rows``.
    """
    if ref is None:
        return
    if ref.kind != ("resource" if resource else "modeled") or ref.partition is not None:
        raise RefreshInputError("Prior modeled input must be one unpartitioned file")
    group: list[ModeledRow] = []
    previous: tuple[date, tuple[str, ...]] | None = None
    count = 0
    for record in store.records(ref):
        row = modeled_from_record(record, ref.grain)
        if previous is not None and row.key <= previous:
            raise RefreshInputError("Duplicate or unsorted prior modeled keys")
        count += 1
        if count > bounds.prior_rows:
            raise ArtifactLimitError("Prior dataset row bound exceeded")
        if group and row.observation.day != group[0].observation.day:
            yield group[0].observation.day, tuple(group)
            group = []
        group.append(row)
        previous = row.key
    if group:
        yield group[0].observation.day, tuple(group)


def day_walk(
    interval: Interval, prior: Iterator[tuple[date, tuple[ModeledRow, ...]]]
) -> Iterator[tuple[date | None, tuple[ModeledRow, ...]]]:
    """Yield malformed dates first, then each interval or prior day ascending.

    Each day carries its prior rows. The union is merged lazily so only the
    current day group is resident; interval length is checked before this runs.
    """
    yield None, ()  # malformed dates still get dispositions and quality counts

    def interval_days() -> Iterator[date]:
        day = interval.start
        while day <= interval.end:
            yield day
            if day == date.max:
                break
            day += timedelta(days=1)

    days = interval_days()
    current = next(days, None)
    pending = next(prior, None)
    while current is not None or pending is not None:
        if current is not None and (pending is None or current < pending[0]):
            yield current, ()
            current = next(days, None)
        elif pending is not None and (current is None or pending[0] < current):
            yield pending
            pending = next(prior, None)
        else:
            assert current is not None and pending is not None
            yield current, pending[1]
            current = next(days, None)
            pending = next(prior, None)


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
    old: tuple[ModeledRow, ...],
    bounds: RefreshBounds,
    staged: StagedDays,
) -> DayMerge:
    rows = incoming_day(store, day, staged)
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
    return DayMerge(day, merge_partition(modeled, old, bounds), old)
