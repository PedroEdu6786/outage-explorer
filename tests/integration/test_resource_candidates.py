"""Explicit new local pipeline: three files, transient validation and faithful retention."""

import json
import logging
import subprocess
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import localcontext
from fractions import Fraction
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ResourceRequest
from outage_explorer.application.errors import ConnectorReportError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import ResourceBaseline
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.ports.source import SourceError, SourceQuality
from outage_explorer.application.services.connector import CreateResourceCandidate
from outage_explorer.bootstrap import (
    build_facility_verifier,
    build_generator_verifier,
    build_national_verifier,
)
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.refresh import EmptySourceError, Interval, RefreshInputError
from outage_explorer.infrastructure.connector_report import LocalConnectorReports
from outage_explorer.infrastructure.parquet.candidates import ParquetResourceBuilder
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.evidence import collect_resources
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    modeled_record,
    schema_for,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_parquet import (
    ARTIFACT_BOUNDS,
    BOUNDS,
    GRAINS,
    ROOT,
    WINDOW,
    pages,
    raw,
)


def inputs(store, run="source", values=None, interval=WINDOW, page_size=2):
    values = values or {grain: [raw(grain)] for grain in GRAINS}
    return tuple(
        collect_resources(store, pages(grain, values[grain], run, interval, page_size))
        for grain in GRAINS
    )


def build(
    store,
    generation="candidate",
    values=None,
    interval=WINDOW,
    prior=None,
    bounds=BOUNDS,
):
    return ParquetResourceBuilder(store).build_resources(
        generation,
        inputs(store, generation, values, interval),
        bounds,
        prior,
    )


def rows(store, candidate, grain="national"):
    ref = next(ref for ref in candidate.resources if ref.grain == grain)
    return [modeled_from_record(record, grain) for record in store.records(ref)]


def summary(candidate, grain="national"):
    return next(item for item in candidate.summaries if item.grain == grain)


@pytest.fixture
def store(tmp_path):
    return LocalParquetStore(tmp_path / "objects", ARTIFACT_BOUNDS)


def test_exactly_three_files_no_supporting_serialization_and_fresh_verification(
    store, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("supporting artifact serialization")

    monkeypatch.setattr(store, "write", forbidden)
    collected = inputs(store)
    assert list(store.root.iterdir()) == []
    candidate = ParquetResourceBuilder(store).build_resources(
        "candidate", collected, BOUNDS
    )
    assert len(list(store.root.iterdir())) == 3
    assert {ref.kind for ref in candidate.resources} == {"resource"}
    assert all(ref.partition is None for ref in candidate.resources)
    assert not hasattr(candidate, "manifest_object")
    assert not hasattr(candidate, "evidence")
    fresh = LocalParquetStore(store.root, ARTIFACT_BOUNDS)
    ParquetResourceBuilder(fresh).verify_resources(candidate, BOUNDS)
    assert (
        DurableResourceReceipt(
            "candidate",
            candidate.resources,
            candidate.interval,
            candidate.contract_id,
            candidate.transformation_id,
            candidate.base_generation_id,
        ).resources
        == candidate.resources
    )


@pytest.mark.parametrize("grain", GRAINS)
def test_resource_schema_retains_exact_private_fields_and_public_contract(store, grain):
    values = {
        g: [raw(g, capacity="1E2", outage="1.2350", percentOutage="9.87500")]
        for g in GRAINS
    }
    with localcontext() as context:
        context.prec = 6
        candidate = build(store, values=values)
    row = rows(store, candidate, grain)[0]
    assert dict(row.observation.original)["capacity"] == "1E2"
    assert dict(row.observation.original)["outage"] == "1.2350"
    assert row.result.percentage == Fraction(247, 200)
    assert row.origin.run_id == "candidate"
    assert schema_for("resource", grain).metadata[b"kind"] == b"resource"
    assert schema_for("resource", grain).names == schema_for("modeled", grain).names


def test_public_views_over_resource_files_in_bounded_duckdb_subprocess(store):
    candidate = build(store)
    descriptors = []
    for dataset in PUBLIC_DATASETS:
        ref = next(ref for ref in candidate.resources if ref.grain == dataset.grain)
        descriptors.append(
            {
                "id": dataset.id,
                "columns": [column.name for column in dataset.columns],
                "path": str(store.root / ref.object.key),
            }
        )
    script = """
import json, resource, sys
resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
import duckdb
items = json.loads(sys.argv[1])
connection = duckdb.connect(":memory:", config={"threads": 1, "memory_limit": "128MB", "max_temp_directory_size": "16MB", "autoload_known_extensions": False, "autoinstall_known_extensions": False})
connection.execute("SET allowed_paths = [" + ",".join("'" + item["path"].replace("'", "''") + "'" for item in items) + "]")
for item in items:
    names = ", ".join('"' + name + '"' for name in item["columns"])
    path = item["path"].replace("'", "''")
    connection.execute('CREATE VIEW "' + item["id"] + '" AS SELECT ' + names + " FROM read_parquet('" + path + "')")
connection.execute("SET enable_external_access = false")
connection.execute("SET lock_configuration = true")
for item in items:
    result = connection.execute('SELECT * FROM "' + item["id"] + '" LIMIT 100')
    assert [column[0] for column in result.description] == item["columns"]
    assert len(result.fetchall()) == 1
    for private in ("origin", "capacity_source", "identity", "share_numerator"):
        try:
            connection.execute('SELECT "' + private + '" FROM "' + item["id"] + '"')
        except duckdb.BinderException:
            pass
        else:
            raise AssertionError("private column exposed")
print("public views verified")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(descriptors)],
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert result.returncode == 0, result.stderr
    assert "public views verified" in result.stdout


def test_recorded_anomaly_fixtures_have_identical_quality_and_exact_values(store):
    values = {}
    for grain in GRAINS:
        source = json.loads(
            (ROOT / f"data/verification/{grain}-2026-09/{grain}.json").read_text()
        )
        values[grain] = source["response"]["data"]
    interval = Interval(date(2026, 9, 1), date(2026, 9, 30))
    collected = tuple(
        collect_resources(
            store,
            pages(
                grain,
                values[grain],
                "recorded",
                interval,
                500,
                "2850" if grain == "facility" else None,
            ),
        )
        for grain in GRAINS
    )
    candidate = ParquetResourceBuilder(store).build_resources(
        "recorded", collected, replace(BOUNDS, incoming_rows=5000, output_rows=5000)
    )
    assert summary(candidate, "facility").quality.received == 1650
    assert summary(candidate, "facility").observed_entities == 55
    assert summary(candidate, "generator").observed_entities == 95
    assert len(list(store.root.iterdir())) == 3
    for grain, verifier in zip(
        GRAINS,
        (build_national_verifier, build_facility_verifier, build_generator_verifier),
        strict=True,
    ):
        report = verifier().verify(
            str(ROOT / f"data/verification/{grain}-2026-09/manifest.json")
        )
        expected = {
            (item.result.observation.day, item.identity): item.result
            for item in report.coverage
            if item.result is not None
        }
        quality = summary(candidate, grain).quality
        assert quality.received == dict(report.counts)["received"]
        assert quality.selected == dict(report.counts)["selected"]
        for row in rows(store, candidate, grain):
            assert row.result == expected[row.key]
            assert row.observation.original == expected[row.key].observation.original


def test_last_valid_aba_identical_duplicates_and_reason_conservation(store):
    values = {
        g: [
            raw(g),
            raw(g, outage="2"),
            raw(g, capacity="1E2"),
            raw(g, capacity="0", **{"outage-units": "wrong"}),
        ]
        for g in GRAINS
    }
    candidate = build(store, values=values)
    for grain in GRAINS:
        row = rows(store, candidate, grain)[0]
        assert row.origin.source_position == 2
        assert dict(row.observation.original)["capacity"] == "1E2"
        q = summary(candidate, grain).quality
        assert (q.received, q.selected, q.excluded, q.duplicate, q.superseded) == (
            4,
            1,
            1,
            1,
            1,
        )
        assert sum(n for _, n in q.reason_counts) == 2


def test_sequential_refresh_retains_invalid_absent_outside_and_wholly_excluded(store):
    initial = {
        g: [raw(g, period=f"2026-09-0{day}") for day in (1, 2, 3)] for g in GRAINS
    }
    prior = build(store, "old", initial)
    incoming = {g: [raw(g, capacity="0"), raw(g, period="invalid")] for g in GRAINS}
    incoming["national"].append(raw("national", period="2026-09-03", outage="0"))
    candidate = build(
        store,
        "new",
        incoming,
        Interval(date(2026, 9, 2), date(2026, 9, 3)),
        prior.baseline,
    )
    assert candidate.base_generation_id == "old"
    for grain in GRAINS:
        s = summary(candidate, grain)
        assert s.retained_invalid == s.carried_outside_interval == 1
        assert s.retained_absent == (0 if grain == "national" else 1)
        assert s.candidate_count == s.active_count == 3
        for row in rows(store, candidate, grain):
            if grain != "national" or row.observation.day.day != 3:
                old = next(
                    value for value in rows(store, prior, grain) if value.key == row.key
                )
                assert row == old
                assert row.observation.original == old.observation.original
    unchanged = build(
        store,
        "excluded",
        {g: [raw(g, capacity="0")] for g in GRAINS},
        prior=candidate.baseline,
    )
    assert unchanged.outcome == "retained_all_excluded"
    assert unchanged.resources == candidate.resources
    with pytest.raises(ArtifactError):
        _ = unchanged.baseline


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize(
    "excluded",
    [
        (),
        ("national",),
        ("facility",),
        ("generator",),
        ("national", "facility"),
        ("national", "generator"),
        ("facility", "generator"),
        ("national", "facility", "generator"),
    ],
)
def test_route_eligibility_and_exact_retention_for_every_exclusion_combination(
    store, initial, excluded
):
    prior = None if initial else build(store, "old")
    incoming = {
        grain: [raw(grain, capacity="0" if grain in excluded else "100", outage="20")]
        for grain in GRAINS
    }
    if initial and excluded:
        with pytest.raises(RefreshInputError, match="usable output"):
            build(store, "new", incoming)
        return
    candidate = build(store, "new", incoming, prior=None if initial else prior.baseline)
    expected_outcome = "retained_all_excluded" if len(excluded) == 3 else "candidate"
    assert candidate.outcome == expected_outcome
    for grain in GRAINS:
        actual = rows(store, candidate, grain)
        if grain in excluded:
            assert actual == rows(store, prior, grain)
            assert summary(candidate, grain).quality.selected == 0
        else:
            assert actual[0].observation.outage == 20
            assert actual[0].origin.run_id == "new"


@pytest.mark.parametrize("grain", GRAINS)
def test_initial_empty_or_wholly_excluded_route_rejected(store, grain):
    values = {g: [raw(g)] for g in GRAINS}
    values[grain] = []
    with pytest.raises(EmptySourceError):
        build(store, values=values)
    values[grain] = [raw(grain, capacity="0")]
    with pytest.raises(RefreshInputError, match="Initial load"):
        build(store, values=values)


@pytest.mark.parametrize("value", ["1E-13", "1E26", "123456789012345678901234567.12"])
def test_unrepresentable_valid_source_fails_candidate(store, value):
    with pytest.raises(RepresentationError):
        build(store, values={g: [raw(g, capacity=value)] for g in GRAINS})


@pytest.mark.parametrize(
    "fault", ["duplicate", "unsorted", "daily", "old-kind", "missing", "count"]
)
def test_bad_resource_baseline_fails_without_graph_conversion(store, fault):
    prior = build(
        store,
        "old",
        {g: [raw(g, period=f"2026-09-0{d}") for d in (1, 2)] for g in GRAINS},
    )
    refs = prior.resources
    ref = refs[0]
    if fault in ("duplicate", "unsorted"):
        original = list(store.records(ref))
        bad_rows = (
            [original[0], original[0]] if fault == "duplicate" else original[::-1]
        )
        ref = store.write_file("resource", "national", bad_rows)
    elif fault == "daily":
        ref = replace(ref, partition=WINDOW.start)
    elif fault == "old-kind":
        ref = replace(ref, kind="modeled")
    elif fault == "count":
        ref = replace(ref, row_count=3)
    changed = (ref, *refs[1:]) if fault != "missing" else refs[1:]
    with pytest.raises((ArtifactError, RefreshInputError)):
        baseline = ResourceBaseline("old", changed, "contract-v1", "transform-v1")
        ParquetResourceBuilder(store).verify_baseline(baseline, BOUNDS)


def test_candidate_semantic_comparison_rejects_coherent_file_forgery(
    store, monkeypatch
):
    write = store.write_file

    def forged(kind, grain, records):
        records = list(records)
        if grain == "national":
            row = modeled_from_record(records[0], grain)
            altered = raw(grain, outage="50")
            from outage_explorer.domain.observations import (
                SourceRecord,
                assess,
                calculate,
            )

            observation = assess(
                SourceRecord(row.origin.source_position, altered), grain
            ).observation
            records[0] = modeled_record(
                replace(
                    row,
                    observation=observation,
                    result=calculate(observation, row.origin.source_position),
                )
            )
        return write(kind, grain, records)

    monkeypatch.setattr(store, "write_file", forged)
    with pytest.raises(ArtifactError, match="transient merge"):
        build(store)


@pytest.mark.parametrize(
    "field,value", [("received", True), ("excluded", -1), ("selected", 1.0)]
)
def test_candidate_rejects_noninteger_quality(store, field, value):
    candidate = build(store)
    changed = replace(
        candidate,
        summaries=(
            replace(
                candidate.summaries[0],
                quality=replace(candidate.summaries[0].quality, **{field: value}),
            ),
            *candidate.summaries[1:],
        ),
    )
    with pytest.raises(ArtifactError):
        ParquetResourceBuilder(store).verify_resources(changed, BOUNDS)


@pytest.mark.parametrize("days", [30, 183])
def test_long_interval_progress_and_cumulative_row_bounds(store, days, caplog):
    interval = Interval(date(2026, 4, 2), date(2026, 4, 2) + timedelta(days=days - 1))
    values = {
        g: [
            raw(g, period=(interval.start + timedelta(days=n)).isoformat())
            for n in range(days)
        ]
        for g in GRAINS
    }
    with caplog.at_level(logging.INFO, logger="outage_explorer.connector.parquet"):
        candidate = build(store, values=values, interval=interval)
    assert "resource_verify_complete grain=generator" in caplog.text
    assert all(ref.row_count == days for ref in candidate.resources)
    with pytest.raises(ArtifactLimitError, match="Incoming dataset"):
        build(
            store,
            "overfull",
            values,
            interval,
            bounds=replace(BOUNDS, incoming_rows=days - 1),
        )


def test_shared_transient_and_file_budget_rejects_combined_inputs(tmp_path):
    probe = LocalParquetStore(tmp_path / "probe", ARTIFACT_BOUNDS)
    one = collect_resources(probe, pages("national", [raw("national")], "source"))
    store = LocalParquetStore(
        tmp_path / "limited", replace(ARTIFACT_BOUNDS, total_bytes=one.byte_count + 10)
    )
    collect_resources(store, pages("national", [raw("national")], "source"))
    with pytest.raises(ArtifactLimitError, match="aggregate transient"):
        collect_resources(store, pages("facility", [raw("facility")], "source"))
    assert not list(store.root.iterdir())


@pytest.mark.parametrize(
    "change", ["offset", "origin", "json", "after-terminal", "missing-terminal"]
)
def test_transient_input_negative_fixtures_write_nothing(store, change):
    sequence = list(pages("national", [raw("national")], "source"))
    if change == "offset":
        sequence[0] = replace(sequence[0], offset=1)
    elif change == "origin":
        sequence[0] = replace(
            sequence[0], origin=replace(sequence[0].origin, row_index=1)
        )
    elif change == "json":
        sequence[0] = replace(sequence[0], values=(float("nan"),))
    elif change == "missing-terminal":
        sequence.pop()
    else:
        sequence.append(sequence[0])
    with pytest.raises(ArtifactError):
        collect_resources(store, sequence)
    assert not list(store.root.iterdir())


def test_transient_transport_matches_canonical_values_without_serialization(store):
    sequence = list(pages("national", [raw("national")], "source"))
    audit = {
        "version": 1,
        "offset": 0,
        "parameters": sequence[0].parameters,
        "request_id": sequence[0].origin.request_id,
        "received_at": sequence[0].origin.retrieved_at.isoformat(),
        "attempt": 1,
        "failures": [],
        "redacted_paths": [],
        "used": True,
        "envelope": {"response": {"data": list(sequence[0].values), "total": "1"}},
    }
    sequence[0] = replace(sequence[0], transport=(audit,))
    terminal_audit = {
        **audit,
        "offset": 1,
        "request_id": sequence[1].origin.request_id,
        "envelope": {"response": {"data": [], "total": "1"}},
    }
    sequence[1] = replace(sequence[1], transport=(terminal_audit,))
    collected = collect_resources(store, sequence)
    assert collected.rows[0].value == raw("national")
    assert not list(store.root.iterdir())
    audit["envelope"]["response"]["data"] = [raw("national", outage="99")]
    with pytest.raises(ArtifactError, match="canonical transport mismatch"):
        collect_resources(store, sequence)


def test_coordinator_composes_three_files_reports_retry_identity_and_safe_failures(
    store, tmp_path
):
    def source(request):
        values = [raw(request.grain)]
        source = Mock(
            quality=SourceQuality(
                request.grain, request.interval, 1, ("1",), False, False, (), (), ()
            )
        )
        source.pages.return_value = pages(request.grain, values, request.run_id)
        return source

    reports = LocalConnectorReports(tmp_path, "a" * 32, 100_000)
    service = CreateResourceCandidate(
        source, LocalConnectorEvidence(store), ParquetResourceBuilder(store), reports
    )
    request = ResourceRequest(
        WINDOW,
        "source",
        "candidate",
        BOUNDS,
        contract_id="contract-v1",
        transformation_id="transform-v1",
    )
    result = service.run(request)
    assert result.report.outcome == "candidate_verified" and result.report_written
    assert not result.report.published
    candidate = result.report.candidate
    document = json.loads((tmp_path / "runs" / ("a" * 32) / "report.json").read_text())
    assert document["candidate"]["generation_id"] == "candidate"
    assert len(document["candidate"]["resources"]) == 3
    assert "manifest" not in document and "rows" not in json.dumps(document)
    failing = Mock()
    failing.finish.side_effect = ConnectorReportError("private failure detail")
    result = CreateResourceCandidate(
        source, LocalConnectorEvidence(store), ParquetResourceBuilder(store), failing
    ).run(replace(request, generation_id="again"))
    assert result.report.error == "report" and not result.report_written
    assert result.report.candidate is None
    assert candidate is not None
    broken = Mock(side_effect=SourceError("secret transport detail"))
    safe = Mock()
    result = CreateResourceCandidate(
        broken, LocalConnectorEvidence(store), ParquetResourceBuilder(store), safe
    ).run(request)
    assert result.report.error == "retrieval" and result.report.candidate is None
    assert "secret" not in repr(result)


def test_prior_output_and_source_order_bounds_are_enforced_before_release(store):
    prior = build(
        store,
        "prior",
        {g: [raw(g, period=f"2026-09-0{d}") for d in (1, 2, 3)] for g in GRAINS},
    )
    with pytest.raises(ArtifactLimitError, match="Prior dataset"):
        build(
            store, "limited", prior=prior.baseline, bounds=replace(BOUNDS, prior_rows=2)
        )
    with pytest.raises(ArtifactLimitError, match="Output dataset"):
        build(
            store,
            "limited-output",
            prior=prior.baseline,
            bounds=replace(BOUNDS, output_rows=2),
        )
    collected = inputs(store)
    first = collected[0]
    row = first.rows[0]
    changed = replace(
        first, rows=(replace(row, origin=replace(row.origin, source_position=1)),)
    )
    with pytest.raises(ArtifactError, match="source identity/order"):
        ParquetResourceBuilder(store).build_resources(
            "unordered", (changed, *collected[1:]), BOUNDS
        )


def test_resource_file_failure_preserves_baseline_and_cleans_atomic_staging(
    store, monkeypatch
):
    prior = build(store, "prior")
    original = store.write_file

    def failure(kind, grain, records):
        if grain == "facility":
            raise ArtifactError("simulated storage failure")
        return original(kind, grain, records)

    monkeypatch.setattr(store, "write_file", failure)
    with pytest.raises(ArtifactError, match="storage failure"):
        build(store, "failed", prior=prior.baseline)
    ParquetResourceBuilder(store).verify_baseline(prior.baseline, BOUNDS)
    assert not list(store.root.glob(".staging-*"))


def test_failed_page_iterator_cannot_return_partial_transient_input(store):
    def failed():
        yield next(pages("national", [raw("national")], "source"))
        raise SourceError("source page failed")

    with pytest.raises(SourceError):
        collect_resources(store, failed())
    assert not list(store.root.iterdir())


@pytest.mark.parametrize("operation", ["baseline", "candidate"])
@pytest.mark.parametrize("budget", ["total_bytes", "objects"])
def test_fresh_store_charges_all_existing_resource_files(store, operation, budget):
    candidate = build(store)
    total = sum(ref.object.byte_count for ref in candidate.resources)
    limited = LocalParquetStore(
        store.root,
        replace(
            ARTIFACT_BOUNDS,
            **(
                {"total_bytes": total - 1}
                if budget == "total_bytes"
                else {"objects": 2}
            ),
        ),
    )
    builder = ParquetResourceBuilder(limited)
    with pytest.raises(ArtifactLimitError):
        if operation == "baseline":
            builder.verify_baseline(candidate.baseline, BOUNDS)
        else:
            builder.verify_resources(candidate, BOUNDS)


def test_exact_adoption_is_idempotent_and_shares_future_write_and_input_bounds(store):
    candidate = build(store)
    total = sum(ref.object.byte_count for ref in candidate.resources)
    fresh = LocalParquetStore(
        store.root, replace(ARTIFACT_BOUNDS, total_bytes=total, objects=3)
    )
    builder = ParquetResourceBuilder(fresh)
    builder.verify_baseline(candidate.baseline, BOUNDS)
    builder.verify_baseline(candidate.baseline, BOUNDS)
    builder.verify_resources(candidate, BOUNDS)
    # Exact-budget repeated verification succeeds; a new file/input must fail.
    with pytest.raises(ArtifactLimitError):
        fresh.put_immutable((b"extra",))
    with pytest.raises(ArtifactLimitError):
        collect_resources(fresh, pages("national", [raw("national")], "source"))
    builder.verify_resources(candidate, BOUNDS)


def test_adoption_still_checks_digest_schema_and_rows_before_admission(store):
    candidate = build(store)
    ref = candidate.resources[0]
    fresh = LocalParquetStore(store.root, ARTIFACT_BOUNDS)
    with pytest.raises(ArtifactError, match="row count"):
        fresh.adopt_exact(replace(ref, row_count=2))
    with pytest.raises(ArtifactError, match="schema"):
        fresh.adopt_exact(replace(ref, kind="public"))
    content = bytearray((store.root / ref.object.key).read_bytes())
    content[10] ^= 1
    (store.root / ref.object.key).write_bytes(content)
    with pytest.raises(ArtifactError, match="checksum"):
        fresh.adopt_exact(ref)
