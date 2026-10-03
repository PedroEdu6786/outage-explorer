"""Synthetic policy cases, not anomalies observed in the recorded EIA sample."""

from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction

import pytest

from outage_explorer.domain.national import (
    FIELDS,
    SourceRecord,
    assess,
    calculate,
    present_percentage,
    select_daily,
)


def row(**changes):
    return {
        "period": "2026-09-01",
        "capacity": "100",
        "outage": "1.235",
        "percentOutage": "9.876",
        "capacity-units": "megawatts",
        "outage-units": "megawatts",
        "percentOutage-units": "percent",
        **changes,
    }


@pytest.mark.parametrize("name", FIELDS)
@pytest.mark.parametrize("kind", ["missing", "empty", "whitespace", "null", "number"])
def test_each_required_field_must_be_a_nonempty_string(name, kind):
    value = row()
    if kind == "missing":
        del value[name]
    else:
        value[name] = {"empty": "", "whitespace": " \t", "null": None, "number": 1}[
            kind
        ]
    result = assess(SourceRecord(0, value))
    assert result.observation is None
    assert len(result.reasons) == 1
    assert result.reasons[0].field == name


@pytest.mark.parametrize("name", ["capacity", "outage", "percentOutage"])
@pytest.mark.parametrize(
    "value",
    [
        "NaN",
        "sNaN",
        "Infinity",
        "-inf",
        "1_000",
        "1,000",
        "one",
        " 1",
        "1 ",
        "0x10",
        "١",
        "1e999999999999999999999999",
    ],
)
def test_invalid_numbers_are_excluded(name, value):
    result = assess(SourceRecord(0, row(**{name: value})))
    assert result.observation is None
    assert result.reasons[0].code == "invalid_number"


@pytest.mark.parametrize(
    "value",
    [
        "2026-02-29",
        "2026-09-31",
        "20260901",
        "2026-9-1",
        "2026-09-01T00:00:00",
        "not-a-date",
    ],
)
def test_invalid_dates_remain_unassigned(value):
    result = assess(SourceRecord(0, row(period=value)))
    assert result.day is None
    assert result.reasons[0].code == "invalid_date"


@pytest.mark.parametrize(
    "name", ["capacity-units", "outage-units", "percentOutage-units"]
)
def test_units_are_not_inferred_or_coerced(name):
    assert (
        assess(SourceRecord(0, row(**{name: "MW"}))).reasons[0].code
        == "incompatible_unit"
    )


@pytest.mark.parametrize("value", ["0", "-0.0", "-1"])
def test_nonpositive_capacity_is_excluded(value):
    result = assess(SourceRecord(0, row(capacity=value)))
    assert result.observation is None
    assert result.reasons[0].code == "nonpositive_capacity"


@pytest.mark.parametrize("value", [None, [], "text", 42])
def test_nonobject_observations_are_excluded(value):
    assert assess(SourceRecord(0, value)).reasons[0].code == "not_object"


def test_unknown_attributes_and_multiple_reasons_are_preserved():
    result = assess(SourceRecord(0, row(extra="value", capacity="0", outage="bad")))
    assert {(r.field, r.code) for r in result.reasons} == {
        ("extra", "unexpected_attribute"),
        ("capacity", "nonpositive_capacity"),
        ("outage", "invalid_number"),
    }


def test_aba_selection_uses_source_order_and_invalid_last_cannot_displace():
    records = [row(), row(outage="2"), row(capacity="1E2"), row(outage="bad")]
    assessments = [
        assess(SourceRecord(index, value)) for index, value in enumerate(records)
    ]
    ledger = select_daily(list(reversed(assessments)))
    assert [item.status for item in ledger] == [
        "duplicate",
        "superseded",
        "selected",
        "excluded",
    ]
    assert [item.selected_position for item in ledger] == [2, 2, 2, None]
    assert dict(ledger[2].assessment.observation.original)["capacity"] == "1E2"


def test_percentage_only_change_is_a_conflicting_observation():
    ledger = select_daily(
        [
            assess(SourceRecord(0, row())),
            assess(SourceRecord(1, row(percentOutage="8"))),
        ]
    )
    assert [item.status for item in ledger] == ["superseded", "selected"]


def test_identical_rows_collapse_and_days_remain_distinct():
    values = [row(), row(), row(period="2026-09-02")]
    ledger = select_daily(
        [assess(SourceRecord(i, value)) for i, value in enumerate(values)]
    )
    assert [item.status for item in ledger] == ["duplicate", "selected", "selected"]
    assert ledger[1].assessment.observation.day == date(2026, 9, 1)


@pytest.mark.parametrize(
    ("outage", "capacity", "fraction", "display"),
    [
        ("0", "100", Fraction(0), "0.00"),
        ("1", "3", Fraction(1, 3), "33.33"),
        ("1.235", "100", Fraction(247, 20000), "1.24"),
        (
            "1.234999999999999999999999999999999999",
            "100",
            Fraction("0.01234999999999999999999999999999999999"),
            "1.23",
        ),
        ("-1.235", "100", Fraction(-247, 20000), "-1.24"),
        ("200", "100", Fraction(2), "200.00"),
    ],
)
def test_exact_calculation_and_rounding_do_not_depend_on_decimal_context(
    outage, capacity, fraction, display
):
    observation = assess(
        SourceRecord(0, row(outage=outage, capacity=capacity))
    ).observation
    assert observation is not None
    with localcontext() as context:
        context.prec = 3
        result = calculate(observation, 0)
    assert result.fraction == fraction
    assert result.percentage == fraction * 100
    assert result.calculated_display == display
    assert result.reported_display == "9.88"
    assert result.observation.outage == Decimal(outage)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.2349", "1.23"), ("1.235", "1.24"), ("1.2351", "1.24"), ("99.995", "100.00")],
)
def test_halfway_neighbors(value, expected):
    assert present_percentage(Fraction(value)) == expected


def test_nonfinite_parse_result_is_excluded_even_when_decimal_traps_are_disabled():
    with localcontext() as context:
        context.traps[InvalidOperation] = False
        result = assess(SourceRecord(0, row(capacity="1e999999999999999999999999")))
    assert result.observation is None
    assert result.reasons[0].code == "invalid_number"
