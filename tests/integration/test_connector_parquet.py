"""Real local Parquet candidates; these do not exercise S3 or publication."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import localcontext
from fractions import Fraction
from pathlib import Path

import pytest

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import SanitizedPage
from outage_explorer.bootstrap import (
    build_facility_verifier,
    build_generator_verifier,
    build_national_verifier,
)
from outage_explorer.domain.refresh import (
    EmptySourceError,
    Interval,
    Origin,
    RefreshBounds,
    RefreshInputError,
    RefreshLimitError,
)
from outage_explorer.infrastructure.parquet.candidates import ParquetCandidateBuilder
from outage_explorer.infrastructure.parquet.evidence import write_evidence
from outage_explorer.infrastructure.parquet.manifests import load_manifest
from outage_explorer.infrastructure.parquet.schemas import (
    modeled_from_record,
    modeled_record,
)
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore

GRAINS = ("national", "facility", "generator")
WINDOW = Interval(date(2026, 9, 1), date(2026, 9, 3))
BOUNDS = RefreshBounds(1000, 1000, 1000, 15, 1000, 100, 100, 100000, 366, 100000)
ARTIFACT_BOUNDS = ArtifactBounds(100, 100, 2**20, 2**22, 2**29, 10000, 2**18, 20)
ROOT = Path(__file__).resolve().parents[2]


def raw(grain, **changes):
    value = {
        "period": "2026-09-02",
        "capacity": "100",
        "outage": "1.235",
        "percentOutage": "9.875",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        value.update(facility="0046", facilityName="Example")
    if grain == "generator":
        value["generator"] = "01"
    return {**value, **changes}


def pages(grain, rows, run, interval=WINDOW, page_size=2, total=None):
    position = 0
    for index, offset in enumerate(range(0, len(rows) + page_size, page_size)):
        values = tuple(rows[offset : offset + page_size])
        origin = Origin(
            grain,
            run,
            f"{run}-{grain}",
            f"request-{run}-{grain}-{index}",
            f"page-{run}-{grain}-{index}",
            datetime(2026, 10, 2, tzinfo=UTC),
            index,
            0,
            position,
            "contract-v1",
            "transform-v1",
            f"evidence-{run}-{grain}-{index}",
        )
        yield SanitizedPage(
            origin,
            interval,
            position,
            page_size,
            1,
            total or str(len(rows)),
            grain,
            {"frequency": "daily"},
            {"fixture": True},
            "2.1.14",
            values,
        )
        position += len(values)
        if not values:
            break


def evidence(store, run, changes=None, interval=WINDOW, page_size=2):
    values = changes or {grain: [raw(grain)] for grain in GRAINS}
    return tuple(
        write_evidence(store, pages(grain, values[grain], run, interval, page_size))
        for grain in GRAINS
    )


@pytest.fixture
def store(tmp_path):
    return LocalParquetStore(tmp_path / "objects", ARTIFACT_BOUNDS)


@pytest.fixture
def builder(store):
    return ParquetCandidateBuilder(store)


def records(store, refs):
    return [value for ref in refs for value in store.records(ref)]


def models(store, candidate, grain):
    return [
        modeled_from_record(value, grain)
        for ref in candidate.modeled
        if ref.grain == grain
        for value in store.records(ref)
    ]


def summary(candidate, grain="national"):
    return next(value for value in candidate.summaries if value.grain == grain)


def test_real_recorded_replay_matches_existing_verifiers(store, builder):
    interval = Interval(date(2026, 9, 1), date(2026, 9, 30))
    bundles = []
    builders = (
        build_national_verifier,
        build_facility_verifier,
        build_generator_verifier,
    )
    reports = {}
    for grain, verifier in zip(GRAINS, builders, strict=True):
        directory = ROOT / f"data/verification/{grain}-2026-09"
        source = json.loads((directory / f"{grain}.json").read_text())
        reports[grain] = verifier().verify(str(directory / "manifest.json"))
        bundles.append(
            write_evidence(
                store,
                pages(
                    grain,
                    source["response"]["data"],
                    "recorded",
                    interval,
                    page_size=500,
                    total=source["response"]["total"],
                ),
            )
        )
    candidate = builder.build("recorded", bundles, BOUNDS)
    for grain in GRAINS:
        expected = (
            {
                item.result.observation.day: item.result
                for item in reports[grain].coverage
                if item.result is not None
            }
            if grain == "national"
            else {
                (item.result.observation.day, item.identity): item.result
                for item in reports[grain].coverage
                if item.result is not None
            }
        )
        modeled = models(store, candidate, grain)
        assert len(modeled) == dict(reports[grain].counts)["selected"]
        assert (
            summary(candidate, grain).quality.received
            == dict(reports[grain].counts)["received"]
        )
        for row in modeled:
            result = expected[row.observation.day if grain == "national" else row.key]
            assert row.result == result
            assert row.observation.original == result.observation.original
    facility_pages = records(store, candidate.evidence[1].pages)
    assert all(page["source_total"] == "2850" for page in facility_pages)
    assert summary(candidate, "facility").quality.received == 1650
    assert summary(candidate, "facility").observed_entities == 55
    assert summary(candidate, "generator").observed_entities == 95
    assert load_manifest(store, candidate.manifest_object) == candidate
    # A newly constructed store can replay explicit references without listing.
    reopened = LocalParquetStore(store.root, ARTIFACT_BOUNDS)
    ParquetCandidateBuilder(reopened).verify(
        load_manifest(reopened, candidate.manifest_object), BOUNDS
    )


def test_cross_page_aba_exact_values_and_quality(store, builder):
    values = {
        grain: [
            raw(grain),
            raw(grain, outage="2"),
            raw(grain, capacity="1E2"),
            raw(grain, capacity="0", **{"outage-units": "wrong"}),
        ]
        for grain in GRAINS
    }
    candidate = builder.build("aba", evidence(store, "aba", values), BOUNDS)
    for grain in GRAINS:
        row = models(store, candidate, grain)[0]
        assert row.origin.source_position == 2
        assert row.result.percentage == Fraction(247, 200)
        assert dict(row.observation.original)["capacity"] == "1E2"
        quality = summary(candidate, grain).quality
        assert (
            quality.received,
            quality.selected,
            quality.excluded,
            quality.duplicate,
            quality.superseded,
        ) == (4, 1, 1, 1, 1)
        assert sum(count for _, count in quality.reason_counts) == 2
        assert summary(candidate, grain).candidate_count == 1


def test_refresh_retains_invalid_absent_missing_dates_and_outside(store, builder):
    initial_values = {
        grain: [raw(grain, period=f"2026-09-0{day}") for day in (1, 2, 3)]
        for grain in GRAINS
    }
    prior = builder.build("old", evidence(store, "old", initial_values), BOUNDS)
    smaller = Interval(date(2026, 9, 2), date(2026, 9, 3))
    new_values = {
        grain: [raw(grain, capacity="0"), raw(grain, period="invalid")]
        for grain in GRAINS
    }
    new_values["national"].append(raw("national", period="2026-09-03", outage="0"))
    candidate = builder.build(
        "new", evidence(store, "new", new_values, smaller), BOUNDS, prior
    )
    for grain in GRAINS:
        result = summary(candidate, grain)
        assert result.retained_invalid == 1
        assert result.carried_outside_interval == 1
        assert result.retained_absent == (0 if grain == "national" else 1)
        assert result.active_count == result.candidate_count == 3
        for row in models(store, candidate, grain):
            assert row.origin.run_id == (
                "new" if grain == "national" and row.observation.day.day == 3 else "old"
            )
    untouched = [ref for ref in prior.modeled if ref.partition.day == 1]
    assert all(ref in candidate.modeled for ref in untouched)
    ledger = records(store, candidate.ledger)
    retained = [item for item in ledger if item["action"] == "retain_invalid"]
    assert all(item["exclusion_positions"] == [0] for item in retained)
    assert candidate.outcome == "candidate"


def test_valid_replacement_repeated_refresh_and_absent_entity(store, builder):
    prior_values = {grain: [raw(grain)] for grain in GRAINS}
    for grain in ("facility", "generator"):
        prior_values[grain].append(raw(grain, facility="999"))
    prior = builder.build("old", evidence(store, "old", prior_values), BOUNDS)
    for run in ("new", "repeat"):
        incoming = {grain: [raw(grain, outage="25")] for grain in GRAINS}
        candidate = builder.build(run, evidence(store, run, incoming), BOUNDS, prior)
        for grain in GRAINS:
            rows = models(store, candidate, grain)
            assert len(rows) == (1 if grain == "national" else 2)
            assert rows[0].observation.outage == 25
            assert rows[0].origin.run_id == run
            assert summary(candidate, grain).retained_absent == (
                0 if grain == "national" else 1
            )
        prior = candidate


def test_all_excluded_keeps_exact_prior_objects_and_reports_no_publication(
    store, builder
):
    prior = builder.build("old", evidence(store, "old"), BOUNDS)
    values = {
        grain: [raw(grain, capacity="0"), None, {"unrecognized": "row"}]
        for grain in GRAINS
    }
    result = builder.build(
        "excluded", evidence(store, "excluded", values), BOUNDS, prior
    )
    assert result.outcome == "retained_all_excluded"
    assert result.modeled == prior.modeled
    assert all(
        item.quality.excluded == 3 and item.candidate_count == 1
        for item in result.summaries
    )
    assert all(item.retained_invalid == 1 for item in result.summaries)


@pytest.mark.parametrize("grain", GRAINS)
def test_initial_unusable_or_empty_required_route_fails(store, builder, grain):
    values = {key: [raw(key)] for key in GRAINS}
    values[grain] = [raw(grain, capacity="0")]
    with pytest.raises(RefreshInputError, match="Initial load"):
        builder.build("bad", evidence(store, "bad", values), BOUNDS)
    values[grain] = []
    with pytest.raises(EmptySourceError):
        builder.build("empty", evidence(store, "empty", values), BOUNDS)


@pytest.mark.parametrize("number", ["1E-13", "1E26", "123456789012345678901234567.12"])
def test_valid_unrepresentable_measurement_fails_candidate(store, builder, number):
    values = {grain: [raw(grain, capacity=number)] for grain in GRAINS}
    bundles = evidence(store, "numbers", values)
    with pytest.raises(RepresentationError):
        builder.build("numbers", bundles, BOUNDS)


def test_projection_overflow_fails_candidate(store, builder):
    values = {grain: [raw(grain, capacity="1E-12", outage="1E25")] for grain in GRAINS}
    with pytest.raises(RepresentationError):
        builder.build("projection", evidence(store, "projection", values), BOUNDS)


def test_extreme_exact_decimal_roundtrip_ignores_decimal_context(store, builder):
    values = {
        grain: [
            raw(
                grain,
                capacity="99999999999999999999999999.999999999999",
                outage="-1.2300000000000",
                percentOutage="+1E-12",
            )
        ]
        for grain in GRAINS
    }
    with localcontext() as context:
        context.prec = 6
        result = builder.build("exact", evidence(store, "exact", values), BOUNDS)
    for grain in GRAINS:
        row = models(store, result, grain)[0]
        assert row.observation.original == tuple(
            (name, values[grain][0][name]) for name, _ in row.observation.original
        )
        assert row.result.fraction == Fraction(-123, 100) / Fraction(
            values[grain][0]["capacity"]
        )


@pytest.mark.parametrize(
    "fault", ["duplicate", "wrong_partition", "missing", "wrong_count", "summary"]
)
def test_whole_manifest_integrity_faults_rejected(store, builder, fault):
    valid = builder.build("valid", evidence(store, "valid"), BOUNDS)
    ref = valid.modeled[0]
    if fault == "duplicate":
        changed = replace(valid, modeled=(*valid.modeled, ref))
    elif fault == "wrong_partition":
        changed = replace(
            valid, modeled=(replace(ref, partition=WINDOW.start), *valid.modeled[1:])
        )
    elif fault == "missing":
        changed = replace(valid, modeled=valid.modeled[1:])
    elif fault == "wrong_count":
        changed = replace(
            valid, modeled=(replace(ref, row_count=2), *valid.modeled[1:])
        )
    else:
        changed = replace(
            valid,
            summaries=(
                replace(valid.summaries[0], candidate_count=99),
                *valid.summaries[1:],
            ),
        )
    with pytest.raises((ArtifactError, RefreshInputError)):
        builder.verify(replace(changed, manifest_object=None), BOUNDS)


def test_coherent_forged_values_cannot_reuse_real_origin(store, builder):
    valid = builder.build("valid", evidence(store, "valid"), BOUNDS)
    other_values = {grain: [raw(grain, outage="50")] for grain in GRAINS}
    other = builder.build("other", evidence(store, "other", other_values), BOUNDS)
    forged = replace(
        models(store, other, "national")[0],
        origin=models(store, valid, "national")[0].origin,
    )
    forged_ref = store.write(
        "modeled", "national", forged.observation.day, [modeled_record(forged)]
    )
    changed = replace(
        valid, modeled=(*forged_ref, *valid.modeled[1:]), manifest_object=None
    )
    with pytest.raises(ArtifactError, match="replay or merge"):
        builder.verify(changed, BOUNDS)


def test_ledger_forgery_with_correct_hash_and_schema_rejected(store, builder):
    valid = builder.build("valid", evidence(store, "valid"), BOUNDS)
    ref = valid.ledger[0]
    values = records(store, (ref,))
    values[0]["action"] = "retain_absent"
    new_refs = store.write("ledger", ref.grain, ref.partition, values)
    with pytest.raises(ArtifactError, match="replay or merge"):
        builder.verify(
            replace(valid, ledger=(*new_refs, *valid.ledger[1:]), manifest_object=None),
            BOUNDS,
        )


def test_inherited_evidence_cannot_be_omitted(store, builder):
    prior = builder.build("old", evidence(store, "old"), BOUNDS)
    values = {grain: [raw(grain, capacity="0")] for grain in GRAINS}
    candidate = builder.build("new", evidence(store, "new", values), BOUNDS, prior)
    with pytest.raises(ArtifactError, match="pinned manifest"):
        builder.verify(
            replace(candidate, inherited_evidence=(), manifest_object=None), BOUNDS
        )


def test_duplicate_keys_split_between_different_files_fail(store, builder):
    prior = builder.build("old", evidence(store, "old"), BOUNDS)
    changed = modeled_record(models(store, prior, "national")[0])
    # Different content/hash while retaining the same natural key.
    changed["origin"] = {**changed["origin"], "run_id": "forged"}
    extra = store.write("modeled", "national", date(2026, 9, 2), [changed])
    malformed_base = replace(
        prior,
        modeled=(prior.modeled[0], *extra, *prior.modeled[1:]),
        manifest_object=None,
    )
    with pytest.raises(ArtifactError):
        builder.verify(malformed_base, BOUNDS)
    candidate = builder.build("new", evidence(store, "new"), BOUNDS, prior)
    with pytest.raises(ArtifactError, match="pinned manifest"):
        builder.verify(
            replace(
                candidate, base_modeled=malformed_base.modeled, manifest_object=None
            ),
            BOUNDS,
        )


def test_many_dates_exceed_group_bound_in_total_but_stream_successfully(store, builder):
    interval = Interval(date(2026, 8, 1), date(2026, 8, 20))
    values = {
        grain: [
            raw(grain, period=(interval.start + timedelta(days=day)).isoformat())
            for day in range(20)
        ]
        for grain in GRAINS
    }
    small_groups = replace(BOUNDS, incoming_rows=2, prior_rows=2, output_rows=2)
    prior = builder.build(
        "history", evidence(store, "history", values, interval), small_groups
    )
    fresh_interval = Interval(date(2026, 9, 1), date(2026, 9, 3))
    new = builder.build(
        "fresh", evidence(store, "fresh", interval=fresh_interval), small_groups, prior
    )
    assert all(
        summary.candidate_count == 21 and summary.carried_outside_interval == 20
        for summary in new.summaries
    )
    assert all(ref in new.modeled for ref in prior.modeled)


def test_one_overfull_complete_day_fails_without_truncation(store, builder):
    values = {grain: [raw(grain), raw(grain), raw(grain)] for grain in GRAINS}
    with pytest.raises(RefreshLimitError, match="incoming rows"):
        builder.build(
            "large", evidence(store, "large", values), replace(BOUNDS, incoming_rows=2)
        )


def test_staging_or_manifest_byte_budget_fails_explicitly(tmp_path):
    store = LocalParquetStore(tmp_path, replace(ARTIFACT_BOUNDS, total_bytes=500))
    with pytest.raises(ArtifactLimitError):
        evidence(store, "limited")


def test_persisted_manifest_cannot_be_silently_changed(store, builder):
    candidate = builder.build("valid", evidence(store, "valid"), BOUNDS)
    with pytest.raises(ArtifactError, match="Persisted manifest"):
        builder.verify(replace(candidate, generation_id="different"), BOUNDS)


@pytest.mark.parametrize(
    "field,value", [("received", True), ("selected", -1), ("received", 1.0)]
)
def test_rehashed_manifest_rejects_noninteger_or_negative_quality(
    store, builder, field, value
):
    candidate = builder.build("valid", evidence(store, "valid"), BOUNDS)
    document = json.loads(b"".join(store.read(candidate.manifest_object)))
    document["summaries"][0]["quality"][field] = value
    payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    reference = store.put_immutable((payload,))
    with pytest.raises(ArtifactError, match="manifest"):
        load_manifest(store, reference)


def test_immutable_base_manifest_prevents_dropped_history(store, builder):
    prior = builder.build("old", evidence(store, "old"), BOUNDS)
    candidate = builder.build("new", evidence(store, "new"), BOUNDS, prior)
    with pytest.raises(ArtifactError, match="pinned manifest"):
        builder.verify(
            replace(
                candidate, base_modeled=candidate.base_modeled[1:], manifest_object=None
            ),
            BOUNDS,
        )
