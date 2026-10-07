"""Bounded day groups and sorted history scans for local candidate construction."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from outage_explorer.application.ports.artifacts import (
    ArtifactLimitError,
    ArtifactRef,
)
from outage_explorer.domain.observations import parse_day
from outage_explorer.domain.refresh import (
    IncomingRow,
    Interval,
    MergedPartition,
    ModeledRow,
    RefreshBounds,
    RefreshInputError,
)
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore


def row_day(row: IncomingRow) -> date | None:
    value = row.value
    if not isinstance(value, Mapping):
        return None
    period = value.get("period")
    return parse_day(period) if isinstance(period, str) else None


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
