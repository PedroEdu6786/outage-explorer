"""Long intervals verify exact three-file results and preserve prior origins."""

from dataclasses import replace
from datetime import date, timedelta

import pytest

from outage_explorer.application.ports.artifacts import ArtifactLimitError
from outage_explorer.domain.refresh import Interval
from outage_explorer.infrastructure.parquet.candidates import ParquetResourceBuilder
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_parquet import (
    ARTIFACT_BOUNDS,
    BOUNDS,
    GRAINS,
    raw,
)
from tests.integration.test_resource_candidates import build, rows


@pytest.mark.parametrize("days", [30, 183])
def test_long_interval_verification_preserves_original_origins(tmp_path, days):
    interval = Interval(date(2026, 4, 2), date(2026, 4, 2) + timedelta(days=days - 1))
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    values = {
        g: [
            raw(g, period=(interval.start + timedelta(days=n)).isoformat())
            for n in range(days)
        ]
        for g in GRAINS
    }
    prior = build(store, "prior", values, interval)
    retained = build(
        store,
        "retained",
        {
            g: [value | {"capacity": "invalid"} for value in items]
            for g, items in values.items()
        },
        interval,
        prior.baseline,
    )
    assert retained.resources == prior.resources
    assert all(summary.retained_invalid == days for summary in retained.summaries)
    for grain in GRAINS:
        assert rows(store, retained, grain) == rows(store, prior, grain)
    ParquetResourceBuilder(store).verify_resources(prior, BOUNDS)
    with pytest.raises(ArtifactLimitError):
        ParquetResourceBuilder(store).verify_baseline(
            prior.baseline, replace(BOUNDS, prior_rows=days - 1)
        )
    assert not list(tmp_path.glob(".staging-*"))
