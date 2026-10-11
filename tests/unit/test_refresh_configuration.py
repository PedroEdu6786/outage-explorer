"""Refresh snapshot constraints, independent of HTTP and storage."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from outage_explorer.domain.publication import (
    INITIAL_END,
    INITIAL_START,
    RefreshConfiguration,
)


@pytest.fixture
def configuration():
    return RefreshConfiguration(
        start=INITIAL_START,
        end=INITIAL_END,
        max_interval_days=183,
        source_interval_days=183,
        model_interval_days=183,
        candidate_seconds=1800,
        persistence_seconds=1800,
    )


@pytest.mark.parametrize(
    "field",
    [
        "max_interval_days",
        "source_interval_days",
        "model_interval_days",
        "candidate_seconds",
        "persistence_seconds",
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, False, "1800", 1800.0, None])
def test_limits_require_positive_integers(configuration, field, value):
    with pytest.raises(ValueError, match=field):
        RefreshConfiguration.model_validate(configuration.model_dump() | {field: value})


@pytest.mark.parametrize(
    "field", ["max_interval_days", "source_interval_days", "model_interval_days"]
)
def test_each_day_limit_covers_the_inclusive_interval(configuration, field):
    with pytest.raises(ValueError, match=f"Refresh date range exceeds {field}"):
        RefreshConfiguration.model_validate(configuration.model_dump() | {field: 182})


@pytest.mark.parametrize("workers", [0, 4, -1, True, "2", 2.0, None])
def test_s3_workers_must_be_an_integer_between_one_and_three(configuration, workers):
    with pytest.raises(ValueError):
        RefreshConfiguration.model_validate(
            configuration.model_dump() | {"s3_workers": workers}
        )


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_supported_workers_and_initial_dates_are_valid(configuration, workers):
    RefreshConfiguration.model_validate(
        configuration.model_dump() | {"s3_workers": workers}
    ).validate_initial_load_dates()


def test_initial_policy_does_not_restrict_subsequent_refresh_dates(configuration):
    subsequent = RefreshConfiguration.model_validate(
        configuration.model_dump() | {"start": INITIAL_START + timedelta(days=1)}
    )
    with pytest.raises(ValueError):
        subsequent.validate_initial_load_dates()


def test_reversed_dates_and_unknown_contract_are_rejected(configuration):
    with pytest.raises(ValueError):
        RefreshConfiguration.model_validate(
            configuration.model_dump() | {"start": INITIAL_END + timedelta(days=1)}
        )
    with pytest.raises(ValueError):
        RefreshConfiguration.model_validate(
            configuration.model_dump() | {"contract_version": "v2"}
        )


def test_validation_preserves_the_serializable_snapshot(configuration):
    before = configuration.model_dump()
    configuration.validate_initial_load_dates()
    assert configuration.model_dump() == before


def test_configuration_is_frozen(configuration):
    with pytest.raises(ValidationError, match="frozen"):
        configuration.s3_workers = 1


def test_durable_json_round_trip(configuration):
    payload = configuration.model_dump(mode="json")
    assert payload["start"] == "2026-04-02"
    assert payload["end"] == "2026-10-01"
    assert (
        RefreshConfiguration.model_validate_json(configuration.model_dump_json())
        == configuration
    )


@pytest.mark.parametrize("field", ["start", "end"])
def test_python_dates_are_strict(configuration, field):
    with pytest.raises(ValidationError, match=field):
        RefreshConfiguration.model_validate(
            configuration.model_dump() | {field: "2026-04-02"}
        )


def test_unknown_fields_are_rejected(configuration):
    with pytest.raises(ValidationError, match="unexpected"):
        RefreshConfiguration.model_validate(
            configuration.model_dump() | {"unexpected": 1}
        )
