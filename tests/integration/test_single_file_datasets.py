"""Single-file modeled/public dataset contracts: schemas, writer and manifest v2."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import pyarrow.parquet as pq
import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    GrainSummary,
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
    Quality,
    RefreshBounds,
    RefreshInputError,
)
from outage_explorer.infrastructure.parquet.manifests import (
    load_manifest,
    manifest_bytes,
    persist_manifest,
    validate_manifest,
)
from outage_explorer.infrastructure.parquet.partitions import day_walk, prior_days
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
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
    modeled = schema_for("modeled", dataset.grain)
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
def test_modeled_and_public_files_are_single_objects_with_bounded_row_groups(
    tmp_path, grain
):
    store = LocalParquetStore(tmp_path, BOUNDS)
    modeled = records(grain)
    modeled_ref = store.write_file("modeled", grain, modeled)
    public_ref = store.write_file("public", grain, (public_record(r) for r in modeled))
    for ref, kind in ((modeled_ref, "modeled"), (public_ref, "public")):
        assert (ref.kind, ref.grain, ref.partition) == (kind, grain, None)
        assert ref.row_count == 5 and ref.schema_version == "1"
        assert len(list(tmp_path.glob("[0-9a-f]" * 64))) == 2
        store.verify(ref)
        with pq.ParquetFile(tmp_path / ref.object.key) as source:
            assert source.metadata.num_row_groups == 3
            assert (
                max(source.metadata.row_group(i).num_rows for i in range(3))
                <= BOUNDS.row_group_rows
            )
    assert list(store.records(modeled_ref)) == modeled
    assert [modeled_from_record(r, grain) for r in store.records(modeled_ref)]
    assert [r["period"] for r in store.records(public_ref)] == [
        r["period"] for r in modeled
    ]


def test_public_files_keep_statistics_and_modeled_files_do_not(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    modeled = records("national")
    refs = {
        "modeled": store.write_file("modeled", "national", modeled),
        "public": store.write_file(
            "public", "national", (public_record(r) for r in modeled)
        ),
    }
    for kind, ref in refs.items():
        with pq.ParquetFile(tmp_path / ref.object.key) as source:
            statistics = source.metadata.row_group(0).column(0).statistics
            assert (statistics is not None) is (kind == "public")
            if statistics is not None:
                assert statistics.min == date(2026, 9, 1)
                assert statistics.max == date(2026, 9, 2)


def test_write_file_is_deterministic_for_identical_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    rows = records("facility")
    assert store.write_file("modeled", "facility", rows) == store.write_file(
        "modeled", "facility", rows
    )


def test_write_file_rejects_empty_oversized_and_mismatched_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    with pytest.raises(ArtifactError, match="Empty"):
        store.write_file("modeled", "national", [])
    assert not list(tmp_path.glob("[0-9a-f]" * 64))
    small = LocalParquetStore(tmp_path / "small", replace(BOUNDS, file_bytes=500))
    with pytest.raises(ArtifactLimitError):
        small.write_file("modeled", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.write_file("public", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.write_file("modeled", "generator", records("national"))


def build_manifest(store, base=None):
    modeled, public, summaries = [], [], []
    for grain in GRAINS:
        rows = records(grain)
        modeled.append(store.write_file("modeled", grain, rows))
        public.append(
            store.write_file("public", grain, (public_record(r) for r in rows))
        )
        summaries.append(
            GrainSummary(
                grain,
                Quality(5, 5, 0, 0, 0, ()),
                5,
                5,
                0,
                0,
                0,
                1,
                5,
                5,
                date(2026, 9, 1),
                date(2026, 9, 5),
            )
        )
    return CandidateManifest(
        "generation",
        None,
        INTERVAL,
        (),
        (),
        (),
        tuple(modeled),
        tuple(public),
        (),
        (),
        tuple(summaries),
        "candidate",
        "contract1",
        "transform1",
    )


def test_manifest_v2_round_trips_single_files_and_period_coverage(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    manifest = persist_manifest(store, build_manifest(store))
    assert manifest.schema_version == "2"
    loaded = load_manifest(store, manifest.manifest_object)
    assert loaded == manifest
    assert loaded.public == manifest.public and len(loaded.public) == 3
    assert [s.first_period for s in loaded.summaries] == [date(2026, 9, 1)] * 3
    assert [s.last_period for s in loaded.summaries] == [date(2026, 9, 5)] * 3


def test_manifest_v1_is_rejected_explicitly_on_encode_and_load(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    manifest = build_manifest(store)
    with pytest.raises(ArtifactError, match="schema version"):
        validate_manifest(replace(manifest, schema_version="1"))
    legacy = json.loads(manifest_bytes(manifest))
    legacy["schema_version"] = "1"
    legacy.pop("public")
    stored = store.put_immutable((json.dumps(legacy).encode(),))
    with pytest.raises(ArtifactError, match="schema version"):
        load_manifest(store, stored)


def test_manifest_rejects_daily_partitions_and_incomplete_file_sets(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    manifest = build_manifest(store)
    validate_manifest(manifest)
    dated = replace(manifest.modeled[0], partition=date(2026, 9, 1))
    with pytest.raises(ArtifactError, match="single unpartitioned"):
        validate_manifest(replace(manifest, modeled=(dated, *manifest.modeled[1:])))
    with pytest.raises(ArtifactError, match="single unpartitioned"):
        validate_manifest(replace(manifest, base_modeled=(dated,)))
    with pytest.raises(ArtifactError, match="exactly one modeled"):
        validate_manifest(replace(manifest, modeled=manifest.modeled[:2]))
    with pytest.raises(ArtifactError, match="exactly one modeled"):
        validate_manifest(replace(manifest, modeled=manifest.modeled * 2))
    with pytest.raises(ArtifactError, match="exactly one public"):
        validate_manifest(replace(manifest, public=()))
    with pytest.raises(ArtifactError, match="exactly one modeled"):
        validate_manifest(replace(manifest, base_modeled=manifest.modeled[:1]))
    with pytest.raises(ArtifactError, match="single unpartitioned"):
        validate_manifest(replace(manifest, public=manifest.modeled))
    shrunk = replace(manifest.public[0], row_count=4)
    with pytest.raises(ArtifactError, match="row counts differ"):
        validate_manifest(replace(manifest, public=(shrunk, *manifest.public[1:])))


def test_manifest_accepts_prior_generation_base_and_validates_coverage(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    manifest = build_manifest(store)
    validate_manifest(replace(manifest, base_modeled=manifest.modeled))
    summary = manifest.summaries[0]
    for bad in (
        replace(summary, last_period=None),
        replace(summary, first_period=date(2026, 9, 6)),
    ):
        with pytest.raises(ArtifactError, match="period coverage"):
            validate_manifest(
                replace(manifest, summaries=(bad, *manifest.summaries[1:]))
            )


def test_physical_public_file_rejects_modeled_schema(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    ref = store.write_file("modeled", "national", records("national"))
    with pytest.raises(ArtifactError):
        store.verify(replace(ref, kind="public"))


PRIOR_BOUNDS = RefreshBounds(1000, 5, 1000, 15, 1000, 100, 100, 100000, 366, 100000)


def groups(store, ref, bounds=PRIOR_BOUNDS):
    return [(day, len(rows)) for day, rows in prior_days(store, ref, bounds)]


def test_prior_days_streams_ascending_day_groups_and_bounds_dataset_rows(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    ref = store.write_file("modeled", "facility", records("facility", range(1, 6)))
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
    ref = store.write_file("modeled", "facility", same_day)
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
    ref = store.write_file("modeled", "national", records("national", (2, 4)))
    interval = Interval(date(2026, 9, 1), date(2026, 9, 4))
    carried = {
        day: len(old)
        for day, old in day_walk(interval, prior_days(store, ref, PRIOR_BOUNDS))
    }
    assert carried == {
        None: 0,
        date(2026, 9, 1): 0,
        date(2026, 9, 2): 1,
        date(2026, 9, 3): 0,
        date(2026, 9, 4): 1,
    }
