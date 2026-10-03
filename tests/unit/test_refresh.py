"""Bounded synthetic refresh partitions, not live or publication evidence."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from fractions import Fraction

import pytest

from outage_explorer.domain.refresh import (
    EmptySourceError,
    IncomingRow,
    Interval,
    Origin,
    RefreshBounds,
    RefreshInputError,
    RefreshLimitError,
    merge_partition,
    model_partition,
    refresh_facts,
)

WINDOW = Interval(date(2024, 2, 28), date(2024, 3, 1))
BOUNDS = RefreshBounds(20, 20, 20, 15, 100, 40, 40, 100, 40, 100)


def raw(grain="national", **changes):
    result = {
        "period": "2024-02-29",
        "capacity": "100",
        "outage": "1.235",
        "percentOutage": "9.875",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
    }
    if grain != "national":
        result.update(facility="0046", facilityName="Example")
    if grain == "generator":
        result["generator"] = "01"
    return {**result, **changes}


def source(value=None, *, grain="national", position=0, run="new", **changes):
    origin = Origin(
        grain,
        run,
        f"retrieval-{run}",
        f"request-{position // 2}",
        f"page-{position // 2}",
        datetime(2024, 3, 2, tzinfo=UTC),
        position // 2,
        position % 2,
        position,
        "contract-v1",
        "transform-v1",
        f"evidence-{run}-{position // 2}",
    )
    return IncomingRow(origin, raw(grain, **changes) if value is None else value)


def model(items, grain="national", bounds=BOUNDS, interval=WINDOW):
    return model_partition(grain, interval, items, bounds)


def prior(grain="national", **changes):
    return model([source(grain=grain, run="old", **changes)], grain).rows[0]


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_cross_page_aba_uses_source_order_with_later_invalid(grain):
    items = [
        source(grain=grain, position=0),
        source(grain=grain, position=1, outage="2"),
        source(grain=grain, position=2, capacity="1E2"),
        source(grain=grain, position=3, capacity="0"),
    ]
    result = model(reversed(items), grain)
    assert [d.disposition.status for d in result.decisions] == [
        "duplicate",
        "superseded",
        "selected",
        "excluded",
    ]
    assert [d.origin.page_index for d in result.decisions] == [0, 0, 1, 1]
    assert [d.disposition.selected_position for d in result.decisions] == [
        2,
        2,
        2,
        None,
    ]
    assert result.rows[0].origin == items[2].origin
    assert dict(result.rows[0].observation.original)["capacity"] == "1E2"
    assert result == model(items, grain)
    assert result.quality.received == 4
    assert result.quality.selected == result.quality.excluded == 1
    assert result.quality.duplicate == result.quality.superseded == 1


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_opaque_keys_and_names_are_independent(grain):
    items = [
        source(grain=grain, position=0),
        source(grain=grain, position=1, facility="46"),
        source(grain=grain, position=2, facilityName="Renamed"),
    ]
    if grain == "generator":
        items.append(source(grain=grain, position=3, generator="1"))
    result = model(items, grain)
    assert len(result.rows) == (3 if grain == "generator" else 2)
    assert result.rows[0].observation.facility_name == "Renamed"
    assert result.decisions[0].disposition.status == "superseded"


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_valid_replacement_is_idempotent_and_preserves_new_origin(grain):
    older = prior(grain)
    incoming = model([source(grain=grain, outage="25")], grain)
    merged = merge_partition(incoming, [older], BOUNDS)
    assert merged.rows == incoming.rows
    assert merged.rows[0].origin.run_id == "new"
    assert merged.rows[0].observation.outage == Decimal("25")
    assert merge_partition(incoming, merged.rows, BOUNDS) == merged
    assert merged.candidate_count == 1
    assert merged.active_count == 1
    assert not merged.retained_invalid_keys


def test_retained_invalid_origin_counts_are_distinct_from_outside_and_absent():
    old = prior()
    absent = prior(period="2024-02-28")
    outside = model(
        [source(run="old", period="2024-02-27")],
        interval=Interval(date(2024, 2, 27), date(2024, 2, 27)),
    ).rows[0]
    incoming = model(
        [
            source(position=0, capacity="0"),
            source(position=1, capacity="bad"),
            source(position=2, period="2024-03-01", outage="0"),
            source(position=3, period="not-a-date", outage="bad"),
        ]
    )
    merged = merge_partition(incoming, [old, outside, absent], BOUNDS)
    assert next(row for row in merged.rows if row.key == old.key) is old
    assert merged.retained_invalid_keys == {old.key}
    assert merged.carried_outside_keys == {outside.key}
    assert merged.absent_prior_rows == (absent,)
    assert merged.candidate_count == 4
    assert merged.retained_absent_keys == {absent.key}
    assert next(row for row in merged.rows if row.key == absent.key) is absent
    assert merged.active_count == 3
    assert incoming.quality.excluded == 3
    assert sum(count for _, count in incoming.quality.reason_counts) == 4
    assert len(merged.rows) == incoming.quality.selected + 1 + 1 + 1
    resolved = merge_partition(incoming, [old, outside], BOUNDS)
    assert resolved.candidate_count == 3


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_unknown_invalid_identity_cannot_match_old_row(grain):
    old = prior(grain)
    incoming = model([source(grain=grain, facility=" 0046", capacity="0")], grain)
    merged = merge_partition(incoming, [old], BOUNDS)
    assert not incoming.excluded_keys
    assert not merged.retained_invalid_keys
    assert merged.absent_prior_rows == (old,)
    assert incoming.quality.excluded == 1
    assert sum(count for _, count in incoming.quality.reason_counts) == 2


def test_incoming_valid_winner_overrides_identifiable_invalid_fallback():
    incoming = model(
        [source(position=0, capacity="0"), source(position=1, outage="75")]
    )
    merged = merge_partition(incoming, [prior()], BOUNDS)
    assert merged.rows == incoming.rows
    assert not merged.retained_invalid_keys


@pytest.mark.parametrize(
    "invalid_grains", [set(), {"facility"}, {"national", "facility", "generator"}]
)
def test_three_grain_facts_distinguish_partial_and_all_excluded(invalid_grains):
    partitions = []
    for grain in ("national", "facility", "generator"):
        value = "0" if grain in invalid_grains else "100"
        incoming = model([source(grain=grain, capacity=value)], grain)
        partitions.append(merge_partition(incoming, [prior(grain)], BOUNDS))
    facts = refresh_facts(reversed(partitions))
    assert set(facts.all_excluded_grains) == invalid_grains
    assert facts.all_excluded is (len(invalid_grains) == 3)
    assert facts.retain_active_without_publication is facts.all_excluded
    assert not facts.absent_prior_keys
    assert facts.mode == "refresh"
    assert facts.transformation_eligible is (len(invalid_grains) < 3)


def test_empty_missing_duplicate_or_misaligned_routes_fail():
    with pytest.raises(EmptySourceError):
        model([])
    partition = merge_partition(model([source()]), [], BOUNDS)
    for parts in ([], [partition], [partition] * 3, [partition] * 4):
        with pytest.raises(RefreshInputError):
            refresh_facts(parts)
    parts = [partition]
    for grain in ("facility", "generator"):
        incoming = model(
            [source(grain=grain)],
            grain,
            interval=Interval(date(2024, 2, 29), date(2024, 2, 29)),
        )
        parts.append(merge_partition(incoming, [], BOUNDS))
    with pytest.raises(RefreshInputError, match="intervals"):
        refresh_facts(parts)


def test_absence_facts_preserve_grain_and_candidate_vs_active_counts():
    parts = []
    for grain in ("national", "facility", "generator"):
        incoming = model([source(grain=grain)], grain)
        parts.append(
            merge_partition(incoming, [prior(grain, period="2024-02-28")], BOUNDS)
        )
    facts = refresh_facts(parts)
    assert len(facts.absent_prior_keys) == 3
    assert facts.absent_prior_keys[0] == ("national", ((date(2024, 2, 28), ()),))
    assert not facts.all_excluded
    assert all(part.candidate_count == 2 and part.active_count == 1 for part in parts)


@pytest.mark.parametrize(
    ("outage", "capacity", "expected", "display"),
    [
        ("1.235", "100", Fraction(247, 20000), "1.24"),
        ("-1.235", "100", Fraction(-247, 20000), "-1.24"),
        ("0", "3", Fraction(0), "0.00"),
        ("1", "3", Fraction(1, 3), "33.33"),
        ("1E-30", "3E-30", Fraction(1, 3), "33.33"),
        (
            "123456789012345678901234567890",
            "3",
            Fraction(123456789012345678901234567890, 3),
            "4115226300411522630041152263000.00",
        ),
    ],
)
def test_national_arithmetic_is_exact(outage, capacity, expected, display):
    result = model([source(outage=outage, capacity=capacity)]).rows[0].result
    assert result.fraction == expected
    assert result.percentage == expected * 100
    assert result.calculated_display == display
    assert result.reported_display == "9.88"


def test_national_values_do_not_derive_from_detail_rows():
    national = model([source(capacity="100", outage="25")])
    facility = model([source(grain="facility", capacity="3", outage="3")], "facility")
    generator = model(
        [source(grain="generator", capacity="7", outage="-2")], "generator"
    )
    refresh_facts(
        [merge_partition(p, [], BOUNDS) for p in (national, facility, generator)]
    )
    assert national.rows[0].result.fraction == Fraction(1, 4)
    assert facility.rows[0].observation.outage == Decimal("3")
    assert generator.rows[0].observation.outage == Decimal("-2")
    assert facility.rows[0].result.fraction == Fraction(1)
    assert generator.rows[0].result.fraction == Fraction(-2, 7)


def test_coverage_keeps_observed_invalid_entities_and_missing_dates_unfilled():
    incoming = model(
        [
            source(grain="facility", position=0),
            source(
                grain="facility", position=1, facility="A", period="bad", outage="bad"
            ),
            source(
                grain="facility",
                position=2,
                facility="B",
                period="2024-03-01",
                capacity="0",
            ),
        ],
        "facility",
    )
    assert incoming.observed_identities == {("0046",), ("A",), ("B",)}
    assert incoming.observed_dates == {date(2024, 2, 29), date(2024, 3, 1)}
    assert incoming.usable_keys == {(date(2024, 2, 29), ("0046",))}
    assert len(incoming.rows) == 1
    assert incoming.interval == WINDOW


@pytest.mark.parametrize(
    "changes",
    [
        {"capacity": None},
        {"capacity-units": "MW"},
        {"period": "2024-02-30"},
        {"outage": "NaN"},
        {"new_field": "x"},
        {"percentOutage": ""},
    ],
)
def test_validation_exclusions_remain_contract_defined(changes):
    result = model([source(**changes)])
    assert result.quality.excluded == 1
    assert result.quality.selected == 0


@pytest.mark.parametrize(
    "bound,limit,changes",
    [
        ("fields_per_row", 6, {}),
        ("field_chars", 30, {"outage": "1" * 31}),
        ("coefficient_digits", 3, {"outage": "1234"}),
        ("absolute_exponent", 3, {"outage": "1e4"}),
        ("absolute_exponent", 3, {"outage": "1e-4"}),
        ("absolute_exponent", 3, {"outage": "0.0001"}),
        ("interval_days", 2, {}),
        ("reason_occurrences", 1, {"capacity": "0", "outage": "bad"}),
    ],
)
def test_explicit_resource_caps_fail_instead_of_excluding(bound, limit, changes):
    with pytest.raises(RefreshLimitError):
        model([source(**changes)], bounds=replace(BOUNDS, **{bound: limit}))


def test_source_and_reference_size_caps():
    item = source(position=2)
    with pytest.raises(RefreshLimitError, match="source index"):
        model([item], bounds=replace(BOUNDS, source_index=1))
    with pytest.raises(RefreshLimitError, match="origin identifier"):
        model([replace(item, origin=replace(item.origin, evidence_id="x" * 101))])
    with pytest.raises(RefreshLimitError, match="field characters"):
        model([source(value="x" * 101)])


@pytest.mark.parametrize(
    "sign, expected", [("+", Fraction(1, 10)), ("-", Fraction(1, 1000))]
)
def test_arithmetic_preflight_handles_large_exponent_text_without_int_expansion(
    sign, expected
):
    with pytest.raises(RefreshLimitError, match="absolute exponent"):
        model(
            [source(outage="1e" + "9" * 5000)], bounds=replace(BOUNDS, field_chars=6000)
        )
    result = model(
        [source(outage="1e" + sign + "0" * 5000 + "1")],
        bounds=replace(BOUNDS, field_chars=6000),
    )
    assert result.rows[0].result.fraction == expected


def test_incoming_and_prior_iterators_stop_at_first_over_budget_row():
    visits = []

    def incoming():
        for i in range(10):
            visits.append(i)
            yield source(position=i)

    with pytest.raises(RefreshLimitError, match="incoming rows"):
        model(incoming(), bounds=replace(BOUNDS, incoming_rows=2))
    assert visits == [0, 1, 2]
    visits.clear()

    def old_rows():
        for i in range(10):
            visits.append(i)
            yield prior(period=f"2024-02-{28 + i:02d}") if i < 2 else prior()

    with pytest.raises(RefreshLimitError, match="prior rows"):
        merge_partition(model([source()]), old_rows(), replace(BOUNDS, prior_rows=2))
    assert visits == [0, 1, 2]


def test_output_bound_covers_new_and_all_retained_rows():
    incoming = model([source()])
    older = prior(period="2024-02-28")
    with pytest.raises(RefreshLimitError, match="output rows"):
        merge_partition(incoming, [older], replace(BOUNDS, output_rows=1))
    with pytest.raises(RefreshLimitError, match="output rows"):
        model(
            [source(), source(position=1, period="2024-03-01")],
            bounds=replace(BOUNDS, output_rows=1),
        )


def test_duplicate_source_and_prior_keys_or_untrustworthy_prior_fail():
    item = source()
    with pytest.raises(RefreshInputError, match="Duplicate source"):
        model([item, item])
    with pytest.raises(RefreshInputError, match="Duplicate source"):
        model([item, replace(item, origin=replace(item.origin, source_position=1))])
    incoming = model([item])
    old = prior()
    with pytest.raises(RefreshInputError, match="Duplicate prior"):
        merge_partition(incoming, [old, old], BOUNDS)
    with pytest.raises(RefreshInputError, match="valid observation"):
        merge_partition(
            incoming,
            [replace(old, observation=replace(old.observation, capacity=Decimal(0)))],
            BOUNDS,
        )
    with pytest.raises(RefreshInputError, match="derived value"):
        merge_partition(incoming, [replace(old, result=None)], BOUNDS)
    with pytest.raises(RefreshInputError, match="Duplicate incoming"):
        merge_partition(replace(incoming, rows=incoming.rows * 2), [], BOUNDS)


def test_integrity_failures_are_not_row_exclusions():
    with pytest.raises(RefreshInputError, match="outside requested"):
        model([source(period="2023-01-01")])
    with pytest.raises(RefreshInputError, match="Mixed retrieval"):
        model([source(), source(position=1, run="other")])
    with pytest.raises(RefreshInputError, match="grain mismatch"):
        model([source(grain="facility")])
    with pytest.raises(RefreshInputError, match="keys must be strings"):
        model([source(value={1: "value"})])
    item = source()
    with pytest.raises(RefreshInputError, match="timezone"):
        model(
            [
                replace(
                    item, origin=replace(item.origin, retrieved_at=datetime(2024, 3, 2))
                )
            ]
        )
    with pytest.raises(RefreshInputError, match="nonnegative"):
        model([replace(item, origin=replace(item.origin, source_position=-1))])
    with pytest.raises(RefreshInputError, match="nonempty"):
        model([replace(item, origin=replace(item.origin, evidence_id=""))])
    with pytest.raises(RefreshInputError, match="positive integers"):
        replace(BOUNDS, incoming_rows=0)
    with pytest.raises(RefreshInputError, match="precedes"):
        Interval(WINDOW.end, WINDOW.start)


@pytest.mark.parametrize(
    "invalid_grains", [set(), {"facility"}, {"national", "facility", "generator"}]
)
def test_initial_load_requires_usable_incoming_rows_in_every_grain(invalid_grains):
    parts = []
    for grain in ("national", "facility", "generator"):
        incoming = model(
            [source(grain=grain, capacity="0" if grain in invalid_grains else "100")],
            grain,
        )
        parts.append(merge_partition(incoming, [], BOUNDS))
    facts = refresh_facts(parts)
    assert facts.mode == "initial"
    assert facts.transformation_eligible is (not invalid_grains)
    assert not facts.retain_active_without_publication
    assert set(facts.all_excluded_grains) == invalid_grains
    assert all(part.active_count == 0 for part in parts)


def test_incomplete_prior_generation_cannot_be_treated_as_initial_or_refresh():
    parts = []
    for grain in ("national", "facility", "generator"):
        incoming = model([source(grain=grain)], grain)
        parts.append(
            merge_partition(
                incoming, [prior(grain)] if grain == "national" else [], BOUNDS
            )
        )
    with pytest.raises(RefreshInputError, match="all three grains"):
        refresh_facts(parts)


def test_partial_all_excluded_route_retains_entire_old_route_and_other_updates():
    old_facility = (prior("facility"), prior("facility", facility="B"))
    rejected = model([source(grain="facility", capacity="0")], "facility")
    facility = merge_partition(rejected, old_facility, BOUNDS)
    other_parts = []
    for grain in ("national", "generator"):
        incoming = model([source(grain=grain, outage="20")], grain)
        other_parts.append(merge_partition(incoming, [prior(grain)], BOUNDS))
    facts = refresh_facts([facility, *other_parts])
    assert facts.transformation_eligible
    assert not facts.retain_active_without_publication
    assert facts.all_excluded_grains == ("facility",)
    assert facility.rows == old_facility
    assert all(
        actual is original
        for actual, original in zip(facility.rows, old_facility, strict=True)
    )
    assert facility.retained_invalid_keys == {old_facility[0].key}
    assert facility.retained_absent_keys == {old_facility[1].key}
    assert facility.candidate_count == facility.active_count == 2
    assert all(part.rows[0].observation.outage == Decimal("20") for part in other_parts)
    assert all(part.rows[0].origin.run_id == "new" for part in other_parts)


def test_all_excluded_refresh_retains_old_rows_even_when_incoming_keys_are_unknown():
    parts = []
    for grain in ("national", "facility", "generator"):
        old = prior(grain)
        incoming = model([source(grain=grain, period="invalid", capacity="0")], grain)
        part = merge_partition(incoming, [old], BOUNDS)
        assert part.rows == (old,)
        assert part.rows[0] is old
        assert part.retained_absent_keys == {old.key}
        assert not part.retained_invalid_keys
        parts.append(part)
    facts = refresh_facts(parts)
    assert facts.mode == "refresh"
    assert facts.all_excluded
    assert facts.retain_active_without_publication
    assert not facts.transformation_eligible
