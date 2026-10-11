"""Refresh snapshot constraints, independent of HTTP and storage."""

from dataclasses import asdict, replace
from datetime import timedelta

import pytest

from outage_explorer.domain.publication import (
    INITIAL_END,
    INITIAL_START,
    RefreshConfiguration,
)


@pytest.fixture
def configuration():
    return RefreshConfiguration(INITIAL_START, INITIAL_END, 183, 183, 183, 1800, 1800)


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
    with pytest.raises(ValueError, match=f"{field} must be a positive integer"):
        replace(configuration, **{field: value}).validate(initial=False)


@pytest.mark.parametrize(
    "field", ["max_interval_days", "source_interval_days", "model_interval_days"]
)
def test_each_day_limit_covers_the_inclusive_interval(configuration, field):
    with pytest.raises(ValueError, match=f"Refresh date range exceeds {field}"):
        replace(configuration, **{field: 182}).validate(initial=False)


@pytest.mark.parametrize("workers", [0, 4, -1, True, "2", 2.0, None])
def test_s3_workers_must_be_an_integer_between_one_and_three(configuration, workers):
    with pytest.raises(ValueError):
        replace(configuration, s3_workers=workers).validate(initial=False)


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_supported_workers_and_initial_dates_are_valid(configuration, workers):
    replace(configuration, s3_workers=workers).validate(initial=True)


def test_initial_policy_does_not_restrict_subsequent_refresh_dates(configuration):
    subsequent = replace(configuration, start=INITIAL_START + timedelta(days=1))
    subsequent.validate(initial=False)
    with pytest.raises(ValueError):
        subsequent.validate(initial=True)


def test_reversed_dates_and_unknown_contract_are_rejected(configuration):
    with pytest.raises(ValueError):
        replace(configuration, start=INITIAL_END + timedelta(days=1)).validate(
            initial=False
        )
    with pytest.raises(ValueError):
        replace(configuration, contract_version="v2").validate(initial=False)


def test_validation_preserves_the_serializable_snapshot(configuration):
    before = asdict(configuration)
    configuration.validate(initial=True)
    assert asdict(configuration) == before
