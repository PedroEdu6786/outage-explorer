"""Synthetic detail observations; not anomalies in the recorded baseline."""

import pytest

from outage_explorer.application.services.evidence import VerifyBaseline
from outage_explorer.domain.observations import (
    SourceRecord,
    assess,
    calculate,
    fields_for,
    select_daily,
)

from .test_evidence_service import CaptureReport, RecordedRows
from .test_national import row as national_row


def row(grain="facility", **changes):
    return {
        **national_row(),
        "facility": "46",
        "facilityName": "Browns Ferry",
        **({"generator": "1"} if grain == "generator" else {}),
        **changes,
    }


@pytest.mark.parametrize("grain", ["facility", "generator"])
@pytest.mark.parametrize("kind", ["missing", "empty", "whitespace", "null", "number"])
def test_all_detail_fields_required(grain, kind):
    for name in fields_for(grain):
        value = row(grain)
        if kind == "missing":
            del value[name]
        else:
            value[name] = {"empty": "", "whitespace": " \t", "null": None, "number": 1}[
                kind
            ]
        result = assess(SourceRecord(0, value), grain)
        assert result.observation is None
        assert len(result.reasons) == 1
        assert result.reasons[0].field == name


@pytest.mark.parametrize("grain", ["facility", "generator"])
@pytest.mark.parametrize(
    ("name", "value", "reason"),
    [
        ("facility", " 46", "invalid_identifier"),
        ("period", "2026-09-31", "invalid_date"),
        ("capacity", "0", "nonpositive_capacity"),
        ("capacity", "-10", "nonpositive_capacity"),
        ("outage", "NaN", "invalid_number"),
        ("outage", "1_000", "invalid_number"),
        ("percentOutage", "Infinity", "invalid_number"),
        ("capacity-units", "MW", "incompatible_unit"),
        ("outage-units", "kilowatts", "incompatible_unit"),
        ("percentOutage-units", "%", "incompatible_unit"),
        ("new_attribute", "x", "unexpected_attribute"),
    ],
)
def test_detail_validation_uses_shared_contract(grain, name, value, reason):
    result = assess(SourceRecord(0, row(grain, **{name: value})), grain)
    assert result.observation is None
    assert [(r.field, r.code) for r in result.reasons] == [(name, reason)]


def test_generator_identifier_is_opaque_and_scoped_to_facility():
    rows = [
        row("generator", facility="0046", generator="01"),
        row("generator", facility="46", generator="01"),
        row("generator", facility="46", generator="1"),
        row("generator", facility="46", generator="A1"),
    ]
    ledger = select_daily(
        [assess(SourceRecord(i, r), "generator") for i, r in enumerate(rows)]
    )
    assert all(item.status == "selected" for item in ledger)
    assert len({item.assessment.identity for item in ledger}) == 4
    invalid = assess(SourceRecord(4, row("generator", generator="1 ")), "generator")
    assert invalid.identity is None
    assert invalid.reasons[0].code == "invalid_identifier"


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_source_order_selection_is_per_entity_and_name_changes_are_revisions(grain):
    rows = [
        row(grain),
        row(grain, outage="2"),
        row(grain, capacity="1E2"),
        row(grain, capacity="0"),
        row(grain, facility="204"),
        row(grain, facility="204", facilityName="New name"),
    ]
    assessments = [assess(SourceRecord(i, r), grain) for i, r in enumerate(rows)]
    ledger = select_daily(list(reversed(assessments)))
    assert [item.status for item in ledger] == [
        "duplicate",
        "superseded",
        "selected",
        "excluded",
        "superseded",
        "selected",
    ]
    assert [item.selected_position for item in ledger] == [2, 2, 2, None, 5, 5]
    assert ledger[5].assessment.observation.facility_name == "New name"


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_same_name_does_not_merge_facilities_and_percentage_changes_are_revisions(
    grain,
):
    rows = [row(grain), row(grain, percentOutage="100"), row(grain, facility="204")]
    ledger = select_daily(
        [assess(SourceRecord(i, r), grain) for i, r in enumerate(rows)]
    )
    assert [item.status for item in ledger] == ["superseded", "selected", "selected"]


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_detail_arithmetic_is_exact_and_reported_percentage_is_not_an_agreement_gate(
    grain,
):
    observation = assess(SourceRecord(0, row(grain)), grain).observation
    result = calculate(observation, 0)
    assert (result.fraction.numerator, result.fraction.denominator) == (247, 20000)
    assert result.calculated_display == "1.24"
    assert result.reported_display == "9.88"


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_coverage_is_entity_by_date_with_invalid_only_entities_and_unassigned_rows(
    grain,
):
    rows = [
        row(grain, outage="0"),
        row(grain, period="2026-09-02", capacity="0", outage="bad"),
        row(grain, facility="204", capacity="0"),
        row(grain, facility=None),
        row(grain, period="bad-date"),
    ]
    report = VerifyBaseline(RecordedRows(rows), CaptureReport(), grain).verify(
        "synthetic"
    )
    assert len(report.coverage) == 60
    key = ("46", "1") if grain == "generator" else ("46",)
    entries = {(c.period, c.identity): c for c in report.coverage}
    first = entries[("2026-09-01", key)]
    assert first.result.calculated_display == "0.00"
    assert first.excluded_positions == ()  # Unknown identity must not attach here.
    second = entries[("2026-09-02", key)]
    assert second.result is None
    assert second.excluded_positions == (1,)
    assert dict(report.counts) == {
        "received": 5,
        "selected": 1,
        "excluded": 4,
        "duplicate": 0,
        "superseded": 0,
    }
    assert sum(dict(report.reason_counts).values()) == 5
    assert len({c.period for c in report.coverage}) == 30


@pytest.mark.parametrize("grain", ["facility", "generator"])
@pytest.mark.parametrize("rows", [[], [None], [{"period": "2026-09-01"}]])
def test_unknown_roster_keeps_30_unavailable_dates(grain, rows):
    report = VerifyBaseline(RecordedRows(rows), CaptureReport(), grain).verify(
        "synthetic"
    )
    assert len(report.coverage) == 30
    assert all(c.identity == () and c.result is None for c in report.coverage)


@pytest.mark.parametrize("grain", ["facility", "generator"])
def test_all_invalid_identifiable_rows_keep_entity_coverage(grain):
    report = VerifyBaseline(
        RecordedRows([row(grain, capacity="0")]), CaptureReport(), grain
    ).verify("synthetic")
    assert len(report.coverage) == 30
    assert all(c.identity and c.result is None for c in report.coverage)
    assert report.coverage[0].excluded_positions == (0,)
