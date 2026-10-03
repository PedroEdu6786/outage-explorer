"""Real Arrow artifact integrity, bounded evidence replay and decimal round trips."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.domain.observations import SourceRecord, assess, calculate
from outage_explorer.domain.refresh import Interval, ModeledRow, Origin
from outage_explorer.infrastructure.parquet.evidence import (
    replay_evidence,
    verify_evidence,
    write_evidence,
)
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    modeled_record,
    schema_for,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

BOUNDS = ArtifactBounds(2, 2, 100_000, 200_000, 10_000_000, 100, 20_000, 16)
INTERVAL = Interval(date(2026, 9, 1), date(2026, 9, 30))


def origin(grain="national", page=0, position=0):
    return Origin(
        grain,
        "run",
        "retrieval",
        f"request{page}",
        f"page{page}",
        datetime(2026, 10, 1, tzinfo=UTC),
        page,
        0,
        position,
        "contract1",
        "transform1",
        f"evidence{page}",
    )


def page(values, index=0, position=0, grain="national"):
    return SanitizedPage(
        origin(grain, index, position),
        INTERVAL,
        position,
        5000,
        1,
        "2850",
        "sanitized-route",
        {"frequency": "daily"},
        {"warnings": ["sample"]},
        "2",
        tuple(values),
    )


def source(**changes):
    return {
        "period": "2026-09-01",
        "capacity": "+3.0000e0",
        "outage": "1",
        "percentOutage": "33.333333333333",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
        **changes,
    }


def modeled(grain="national", **changes):
    raw = source(**changes)
    if grain != "national":
        raw.update(facility="001", facilityName="Exact name ")
    if grain == "generator":
        raw["generator"] = "01"
    observation = assess(SourceRecord(0, raw), grain).observation
    assert observation is not None
    return ModeledRow(observation, origin(grain), calculate(observation, 0))


def test_evidence_preserves_invalid_json_types_empty_page_and_source_order(tmp_path):
    values = [
        source(),
        None,
        ["invalid", 1, True, 0.5],
        {"outage": False},
        "string",
        42,
    ]
    store = LocalParquetStore(tmp_path, BOUNDS)
    bundle = write_evidence(store, [page(values), page([], 1, len(values))])
    assert len(bundle.raw) == 3
    replay = list(replay_evidence(store, bundle))
    assert [item.value for item in replay] == values
    assert [item.origin.source_position for item in replay] == list(range(len(values)))
    assert [item.origin.row_index for item in replay] == list(range(len(values)))
    pages = [record for ref in bundle.pages for record in store.records(ref)]
    assert pages[1]["returned_count"] == 0
    assert pages[1]["source_total"] == "2850"
    assert pages[1]["raw_refs_json"] == "[]"


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_exact_model_roundtrip_even_under_low_decimal_context(tmp_path, grain):
    with localcontext() as context:
        context.prec = 6
        row = modeled(grain)
        store = LocalParquetStore(tmp_path, BOUNDS)
        records = store.write(
            "modeled", grain, row.observation.day, [modeled_record(row)]
        )
        record = next(store.records(records[0]))
        replay = modeled_from_record(record, grain)
        assert replay == row
        assert replay.observation.original == row.observation.original
        assert record["capacity_mw"] == Decimal(3)
        assert record["calculated_percentage_rounded"] == Decimal("33.33")
        if grain != "national":
            assert record["facility"] == "001"
        if grain == "generator":
            assert record["generator"] == "01"


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity": "1e26"},
        {"outage": "1e-13"},
        {"percentOutage": "1e-13"},
        {"capacity": "1e-12", "outage": "1e25"},
    ],
)
def test_physical_loss_fails_not_excludes(changes):
    row = modeled(**changes)
    with pytest.raises(RepresentationError):
        modeled_record(row)


@pytest.mark.parametrize(
    "field,value",
    [
        ("share_denominator", "2"),
        ("calculated_percentage_display", "33.34"),
        ("capacity_mw", Decimal(4)),
        ("reported_percentage_units", "MW"),
    ],
)
def test_modeled_codec_rejects_disagreement(field, value):
    record = modeled_record(modeled())
    record[field] = value
    with pytest.raises(ArtifactError):
        modeled_from_record(record, "national")


def test_decode_preflights_large_exponent_before_arithmetic():
    record = modeled_record(modeled())
    record["capacity_source"] = "1e999999999"
    with pytest.raises(RepresentationError):
        modeled_from_record(record, "national")


@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), ("tuple",), {1: "integer key"}, Decimal("2")]
)
def test_evidence_requires_finite_json_types(tmp_path, value):
    with pytest.raises(ArtifactError):
        write_evidence(LocalParquetStore(tmp_path, BOUNDS), [page([value])])


@pytest.mark.parametrize(
    "change",
    [
        {"field_bytes": 10},
        {"file_bytes": 100},
        {"total_bytes": 100},
        {"objects": 1},
        {"row_group_bytes": 100},
        {"json_depth": 1},
    ],
)
def test_each_storage_budget_fails_explicitly(tmp_path, change):
    with pytest.raises(ArtifactLimitError):
        write_evidence(
            LocalParquetStore(tmp_path, replace(BOUNDS, **change)), [page([source()])]
        )


def test_bundle_linkage_verified_before_first_replay_yield(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    bundle = write_evidence(store, [page([source()]), page([source(outage="2")], 1, 1)])
    corrupt = replace(bundle, raw=tuple(reversed(bundle.raw)))
    with pytest.raises(ArtifactError, match="linkage"):
        next(replay_evidence(store, corrupt))


def test_corruption_count_schema_and_missing_file_fail_before_yield(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    bundle = write_evidence(store, [page([source()])])
    ref = bundle.raw[0]
    with pytest.raises(ArtifactError, match="row count"):
        next(store.records(replace(ref, row_count=2)))
    with pytest.raises(ArtifactError, match="schema"):
        next(store.records(replace(ref, kind="modeled")))
    with pytest.raises(ArtifactError, match="byte count"):
        next(
            store.records(
                replace(
                    ref,
                    object=replace(ref.object, byte_count=ref.object.byte_count + 1),
                )
            )
        )
    path = tmp_path / ref.object.key
    content = bytearray(path.read_bytes())
    content[10] ^= 1
    path.write_bytes(content)
    with pytest.raises(ArtifactError, match="checksum"):
        next(store.records(ref))
    path.unlink()
    with pytest.raises(ArtifactError, match="unavailable"):
        verify_evidence(store, bundle)


def test_wrong_physical_schema_with_valid_checksum_fails(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    sink = pa.BufferOutputStream()
    pq.write_table(pa.table({"value": ["not raw"]}), sink)
    obj = store.put_immutable([sink.getvalue().to_pybytes()])
    with pytest.raises(ArtifactError, match="schema"):
        store.verify(ArtifactRef(obj, "raw", "national", None, 1))


def test_object_identity_is_immutable_and_path_safe(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    obj = store.put_immutable([b"same", b" bytes"])
    assert store.put_immutable([b"same bytes"]) == obj
    assert b"".join(store.read(obj)) == b"same bytes"
    with pytest.raises(ArtifactError):
        store.verify(replace(obj, key="../arbitrary"))


def test_schema_metadata_is_explicit_for_all_artifacts():
    for grain in ("national", "facility", "generator"):
        for kind in ("raw", "pages", "dispositions", "modeled", "ledger"):
            assert schema_for(kind, grain).metadata == {
                b"kind": kind.encode(),
                b"grain": grain.encode(),
                b"version": b"1",
            }


def test_identical_object_retry_at_exact_budget_is_idempotent(tmp_path):
    store = LocalParquetStore(tmp_path, replace(BOUNDS, total_bytes=4, objects=1))
    obj = store.put_immutable([b"data"])
    assert store.put_immutable([b"data"]) == obj
    with pytest.raises(ArtifactLimitError):
        store.put_immutable([b"next"])
    assert b"".join(store.read(obj)) == b"data"


def test_failed_atomic_install_leaves_no_final_or_staging_object(tmp_path, monkeypatch):
    from outage_explorer.infrastructure.parquet import storage

    store = LocalParquetStore(tmp_path, BOUNDS)
    real_link = storage.os.link

    def fail_link(*args, **kwargs):
        raise OSError("simulated disk fault")

    monkeypatch.setattr(storage.os, "link", fail_link)
    with pytest.raises(ArtifactError, match="persist"):
        store.put_immutable([b"retry me"])
    assert list(tmp_path.iterdir()) == []
    monkeypatch.setattr(storage.os, "link", real_link)
    obj = store.put_immutable([b"retry me"])
    store.verify_object(obj)


def test_oversized_row_groups_from_foreign_artifact_are_rejected(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    bundle = write_evidence(store, [page([source(), source(), source()])])
    rows = [record for ref in bundle.raw for record in store.records(ref)]
    sink = pa.BufferOutputStream()
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema_for("raw", "national")),
        sink,
        row_group_size=3,
    )
    obj = store.put_immutable([sink.getvalue().to_pybytes()])
    with pytest.raises(ArtifactLimitError, match="row group"):
        next(store.records(ArtifactRef(obj, "raw", "national", None, 3)))


def test_page_origin_and_sequence_tampering_fail(tmp_path):
    store = LocalParquetStore(tmp_path, BOUNDS)
    first = page([source()])
    second = page([source()], 1, 1)
    with pytest.raises(ArtifactError, match="ordering"):
        write_evidence(
            store, [first, replace(second, origin=replace(second.origin, row_index=1))]
        )
    with pytest.raises(ArtifactError, match="Mixed"):
        write_evidence(
            store,
            [
                first,
                replace(second, origin=replace(second.origin, retrieval_id="other")),
            ],
        )
    with pytest.raises(ArtifactError, match="terminal"):
        write_evidence(store, [page([]), second])


def test_decode_trims_insignificant_zeros_before_fraction_expansion(monkeypatch):
    from outage_explorer.infrastructure.parquet import schemas

    record = modeled_record(modeled())
    original = "3." + "0" * 100_000
    record["capacity_source"] = original
    record["outage_source"] = "1." + "0" * 100_000
    real_calculate = schemas.calculate
    calls = []

    def bounded_calculate(observation, position):
        assert len(observation.capacity.as_tuple().digits) == 1
        assert len(observation.outage.as_tuple().digits) == 1
        calls.append(position)
        return real_calculate(observation, position)

    monkeypatch.setattr(schemas, "calculate", bounded_calculate)
    restored = schemas.modeled_from_record(record, "national")
    assert dict(restored.observation.original)["capacity"] == original
    assert calls == [0, 0]
