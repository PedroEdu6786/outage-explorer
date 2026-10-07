"""Unified resource file contracts and public projections."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pyarrow.parquet as pq
import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.observations import (
    SourceRecord,
    assess,
    calculate,
)
from outage_explorer.domain.refresh import (
    Interval,
    ModeledRow,
    Origin,
    RefreshBounds,
    RefreshInputError,
)
from outage_explorer.infrastructure.parquet.partitions import day_walk, prior_days
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_record,
    public_record,
    public_schema,
    schema_for,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

BOUNDS = ArtifactBounds(2, 2, 100_000, 1_000_000, 10_000_000, 100, 20_000, 16)
INTERVAL = Interval(date(2026, 9, 1), date(2026, 9, 30))
GRAINS = ("national", "facility", "generator")


def origin(grain, position):
    return Origin(
        grain,
        "run",
        "retrieval",
        "request",
        "page",
        datetime(2026, 10, 1, tzinfo=UTC),
        0,
        position,
        position,
        "contract1",
        "transform1",
        "evidence",
    )


def row(grain, day, facility="001"):
    raw = {
        "period": day.isoformat(),
        "capacity": "+3.0000e0",
        "outage": "1",
        "percentOutage": "33.333333333333",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        raw.update(facility=facility, facilityName="Exact name ")
    if grain == "generator":
        raw["generator"] = "01"
    position = day.day
    observation = assess(SourceRecord(position, raw), grain).observation
    assert observation is not None
    return ModeledRow(
        observation, origin(grain, position), calculate(observation, position)
    )


def records(grain, days=range(1, 6)):
    return [modeled_record(row(grain, date(2026, 9, day))) for day in days]


@pytest.mark.parametrize("dataset", PUBLIC_DATASETS, ids=lambda item: item.id)
def test_public_schema_is_declared_columns_typed_by_modeled_schema(dataset):
    schema = public_schema(dataset.grain)
    modeled = schema_for("resource", dataset.grain)
    assert schema.names == [column.name for column in dataset.columns]
    assert schema_for("public", dataset.grain).equals(schema, check_metadata=True)
    for field in schema:
        assert field.equals(modeled.field(field.name)) and not field.nullable
    assert schema.metadata == {
        b"kind": b"public",
        b"grain": dataset.grain.encode(),
        b"version": b"1",
    }
    assert not {"origin", "identity", "share_numerator"} & set(schema.names)


@pytest.mark.parametrize("grain", GRAINS)
def test_public_record_projects_modeled_values_in_declared_order(grain):
    record = records(grain)[0]
    projected = public_record(record)
    columns = next(item for item in PUBLIC_DATASETS if item.grain == grain).columns
    assert list(projected) == [column.name for column in columns]
    assert all(projected[name] == record[name] for name in projected)
    assert "origin" not in projected
    with pytest.raises(ArtifactError):
        public_record({key: value for key, value in record.items() if key != "period"})
    with pytest.raises(ArtifactError):
        public_record({"period": date(2026, 9, 1)})


@pytest.mark.parametrize("grain", GRAINS)
def test_resource_file_is_single_object_with_bounded_row_groups(tmp_path, grain):
    store = LocalParquetStore(tmp_path, BOUNDS)
    values = records(grain)
    ref = store.write_file("resource", grain, values)
    assert (ref.kind, ref.grain, ref.partition, ref.row_count) == (
        "resource",
        grain,
        None,
        5,
    )
    assert len(list(tmp_path.iterdir())) == 1
    store.verify(ref)
    with pq.ParquetFile(tmp_path / ref.object.key) as source:
        assert source.metadata.num_row_groups == 3
        assert all(
            source.metadata.row_group(i).num_rows <= BOUNDS.row_group_rows
            for i in range(3)
        )
    assert list(store.records(ref)) == values


def test_write_file_is_deterministic_for_identical_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    rows = records("facility")
    assert store.write_file("resource", "facility", rows) == store.write_file(
        "resource", "facility", rows
    )


def test_write_file_rejects_empty_oversized_and_mismatched_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    with pytest.raises(ArtifactError, match="Empty"):
        store.write_file("resource", "national", [])
    assert not list(tmp_path.glob("[0-9a-f]" * 64))
    small = LocalParquetStore(tmp_path / "small", replace(BOUNDS, file_bytes=500))
    with pytest.raises(ArtifactLimitError):
        small.write_file("resource", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.write_file("public", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.write_file("resource", "generator", records("national"))


def test_physical_public_file_rejects_modeled_schema(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    ref = store.write_file("resource", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.verify(replace(ref, kind="public"))


PRIOR_BOUNDS = RefreshBounds(1000, 5, 1000, 15, 1000, 100, 100, 100000, 366, 100000)


def groups(store, ref, bounds=PRIOR_BOUNDS):
    return [
        (day, len(rows)) for day, rows in prior_days(store, ref, bounds, resource=True)
    ]


def test_prior_days_streams_ascending_day_groups_and_bounds_dataset_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    ref = store.write_file("resource", "facility", records("facility", range(1, 6)))
    assert groups(store, ref) == [(date(2026, 9, day), 1) for day in range(1, 6)]
    assert groups(store, None) == []
    with pytest.raises(ArtifactLimitError, match="Prior dataset"):
        groups(store, ref, replace(PRIOR_BOUNDS, prior_rows=4))
    dated = replace(ref, partition=date(2026, 9, 1))
    with pytest.raises(RefreshInputError, match="unpartitioned"):
        groups(store, dated)
    with pytest.raises(RefreshInputError, match="unpartitioned"):
        groups(store, replace(ref, kind="public"))


def test_prior_days_groups_rows_sharing_a_day(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    day = date(2026, 9, 2)
    same_day = [
        modeled_record(row("facility", day, "001")),
        modeled_record(row("facility", day, "002")),
        modeled_record(row("facility", date(2026, 9, 3), "001")),
    ]
    ref = store.write_file("resource", "facility", same_day)
    assert groups(store, ref) == [(day, 2), (date(2026, 9, 3), 1)]


def walk(interval, prior):
    stream = ((day, ()) for day in prior)
    return [day for day, _ in day_walk(interval, stream)]


def test_day_walk_yields_malformed_group_then_ascending_union_of_days():
    interval = Interval(date(2026, 9, 3), date(2026, 9, 5))
    prior = [date(2026, 9, 1), date(2026, 9, 4), date(2026, 9, 8)]
    assert walk(interval, prior) == [
        None,
        date(2026, 9, 1),
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 5),
        date(2026, 9, 8),
    ]
    assert walk(interval, []) == [None, *(date(2026, 9, d) for d in (3, 4, 5))]
    assert walk(Interval(date(2026, 9, 1), date(2026, 9, 1)), [date(2026, 9, 1)]) == [
        None,
        date(2026, 9, 1),
    ]


def test_day_walk_carries_prior_rows_to_their_day_only(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    ref = store.write_file("resource", "national", records("national", (2, 4)))
    interval = Interval(date(2026, 9, 1), date(2026, 9, 4))
    carried = {
        day: len(old)
        for day, old in day_walk(
            interval, prior_days(store, ref, PRIOR_BOUNDS, resource=True)
        )
    }
    assert carried == {
        None: 0,
        date(2026, 9, 1): 0,
        date(2026, 9, 2): 1,
        date(2026, 9, 3): 0,
        date(2026, 9, 4): 1,
    }
