"""Larger source/prior generations fit explicit defaults without live services."""

from datetime import date, timedelta

from outage_explorer.bootstrap import execute_connector
from tests.integration.test_connector_cli import (
    Wire,
    config_file,
    environment,
    inputs,
    row,
)


def test_year_scale_candidate_and_retained_prior_fit_shared_defaults(tmp_path):
    first, last = date(2025, 11, 1), date(2026, 10, 8)
    days = (last - first).days + 1
    rows = {}
    for grain, entities in (("national", 1), ("facility", 55), ("generator", 95)):
        rows[grain] = [
            row(
                grain,
                period=(first + timedelta(days=day)).isoformat(),
                **({"facility": str(entity + 1)} if grain != "national" else {}),
            )
            for day in range(days)
            for entity in range(entities)
        ]
    expected = {grain: len(values) for grain, values in rows.items()}
    assert sum(expected.values()) == 51_642
    # HTTP refresh resolves this span at admission. CLI requires explicit date
    # overrides; only fake-wire pacing is shortened, no capacity is overridden.
    config = config_file(
        tmp_path,
        {
            "source": {"interval_days": days, "request_interval_milliseconds": 1},
            "model": {"interval_days": days},
        },
    )
    wire = Wire(rows)
    first_run = execute_connector(
        inputs(tmp_path, start=str(first), end=str(last), config_path=config),
        environment=environment(),
        transport=wire,
    )
    assert wire.closed
    assert first_run.report.outcome == "candidate_verified", first_run.report.error
    candidate = first_run.report.candidate
    assert {ref.grain: ref.row_count for ref in candidate.resources} == expected
    assert len(wire.calls) > 100  # The former shared page limit cannot fit this run.
    assert not first_run.report.published

    # A subsequent refresh must accept the >30,000-row generator baseline,
    # replace one observation per grain, and retain all absent prior keys.
    wire = Wire(
        {grain: [dict(values[-1], outage="2")] for grain, values in rows.items()}
    )
    rerun = execute_connector(
        inputs(tmp_path, candidate, str(first), str(last), config_path=config),
        environment=environment(),
        transport=wire,
    )
    assert wire.closed
    assert rerun.report.outcome == "candidate_verified", rerun.report.error
    assert {
        ref.grain: ref.row_count for ref in rerun.report.candidate.resources
    } == expected
    assert {
        summary.grain: summary.retained_absent
        for summary in rerun.report.candidate.summaries
    } == {grain: count - 1 for grain, count in expected.items()}
    assert not rerun.report.published
