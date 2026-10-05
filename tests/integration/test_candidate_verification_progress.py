"""Long-interval verification retains exact semantics without repeated raw scans."""

import logging
from datetime import date, timedelta
from time import perf_counter
from unittest.mock import patch

import pytest

from outage_explorer.application.ports.artifacts import ArtifactLimitError
from outage_explorer.domain.refresh import Interval
from outage_explorer.infrastructure.parquet import candidates, partitions
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_parquet import (
    ARTIFACT_BOUNDS,
    BOUNDS,
    GRAINS,
    evidence,
    raw,
)


@pytest.mark.parametrize("days", [30, 183])
def test_long_interval_verification_replay_counts_equivalence(tmp_path, caplog, days):
    interval = Interval(date(2026, 4, 2), date(2026, 4, 2) + timedelta(days=days - 1))
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    bundles = evidence(
        store,
        "long-run",
        {
            grain: [
                raw(grain, period=(interval.start + timedelta(days=n)).isoformat())
                for n in range(days)
            ]
            for grain in GRAINS
        },
        interval,
        page_size=500,
    )
    builder = candidates.ParquetCandidateBuilder(store)
    candidate = builder.build("long-candidate", bundles, BOUNDS)
    with caplog.at_level(logging.INFO, logger="outage_explorer.connector.parquet"):
        with patch.object(
            partitions, "replay_evidence", wraps=partitions.replay_evidence
        ) as scans:
            start = perf_counter()
            builder.verify(candidate, BOUNDS)
            indexed_seconds = perf_counter() - start
            assert scans.call_count == 3
        with patch.object(candidates, "stage_dates", return_value=None):
            with patch.object(
                partitions, "replay_evidence", wraps=partitions.replay_evidence
            ) as scans:
                start = perf_counter()
                builder.verify(candidate, BOUNDS)
                baseline_seconds = perf_counter() - start
                assert scans.call_count == 3 * (days + 1)
    print(
        f"verification days={days} indexed_seconds={indexed_seconds:.3f} baseline_seconds={baseline_seconds:.3f} indexed_scans=3 baseline_scans={3 * (days + 1)}"
    )
    assert "grain_build_started" not in caplog.text
    assert "grain_verify_progress grain=generator" in caplog.text
    assert "grain_verify_complete grain=generator" in caplog.text
    assert candidate == builder.build("long-candidate", bundles, BOUNDS)


def test_verification_index_respects_store_budget_and_cleans_atomic_files(tmp_path):
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    candidate = candidates.ParquetCandidateBuilder(store).build(
        "candidate", evidence(store, "run"), BOUNDS
    )
    bounded = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    bounded._bytes = ARTIFACT_BOUNDS.total_bytes
    with pytest.raises(ArtifactLimitError):
        candidates.ParquetCandidateBuilder(bounded).verify(candidate, BOUNDS)
    assert not list(tmp_path.glob(".staging-*"))
    candidates.ParquetCandidateBuilder(store).verify(candidate, BOUNDS)


def test_retained_history_uses_one_replay_per_bundle_and_original_origins(tmp_path):
    interval = Interval(date(2026, 4, 2), date(2026, 5, 1))
    store = LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)
    rows = {
        grain: [
            raw(grain, period=(interval.start + timedelta(days=n)).isoformat())
            for n in range(30)
        ]
        for grain in GRAINS
    }
    builder = candidates.ParquetCandidateBuilder(store)
    prior = builder.build(
        "prior", evidence(store, "original", rows, interval, 500), BOUNDS
    )
    invalid = {
        grain: [value | {"capacity": "invalid"} for value in values]
        for grain, values in rows.items()
    }
    retained = builder.build(
        "retained", evidence(store, "later", invalid, interval, 500), BOUNDS, prior
    )
    assert retained.modeled == prior.modeled
    with patch.object(
        partitions, "replay_evidence", wraps=partitions.replay_evidence
    ) as scans:
        builder.verify(retained, BOUNDS)
        assert scans.call_count == 6
    assert all(summary.retained_invalid == 30 for summary in retained.summaries)
