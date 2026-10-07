"""Direct descriptor cache reads and public-only views over unified resource files."""

import hashlib
import io
import stat
import threading
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import duckdb
import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    DataUnavailableError,
)
from outage_explorer.application.ports.execution import ExecutionBounds
from outage_explorer.application.services.resource_artifacts import (
    PersistResourceArtifacts,
)
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.duckdb.views import open_restricted
from outage_explorer.infrastructure.local_cache.modeled import (
    ResourceReadSessions,
    VerifiedResourceCache,
)
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.s3.resources import S3ResourceStore
from tests.integration.test_catalog_preview import CACHE
from tests.integration.test_connector_parquet import (
    ARTIFACT_BOUNDS,
    BOUNDS,
    GRAINS,
    raw,
)
from tests.integration.test_resource_candidates import build
from tests.integration.test_s3_artifacts import ControlledS3

EXECUTION = ExecutionBounds(20, 30, 128 * 1024**2, 32 * 1024**2, 1024**2)
DAYS = ("2026-09-01", "2026-09-03")
FILES = {
    AnalyticalGrain.NATIONAL: "national",
    AnalyticalGrain.FACILITY: "facilities",
    AnalyticalGrain.GENERATOR: "generators",
}


class Published:
    """A controlled durable resource generation read through exact descriptors."""

    def __init__(self, tmp_path):
        store = LocalParquetStore(tmp_path / "candidate", ARTIFACT_BOUNDS)
        values = {grain: [raw(grain, period=day) for day in DAYS] for grain in GRAINS}
        candidate = build(store, generation="generation_2", values=values)
        self.client = ControlledS3()
        cancelled = threading.Event()
        workers = BoundedConnectorWorkers(3, cancelled)
        remote = S3ResourceStore(
            self.client,
            "test-bucket",
            "connector/",
            ARTIFACT_BOUNDS,
            cancelled=cancelled,
        )
        receipt = PersistResourceArtifacts(
            LocalConnectorEvidence(store, workers), remote, workers
        ).execute(candidate, BOUNDS)
        self.client.calls.clear()
        coverage = {item.grain: item for item in candidate.summaries}
        self.generation = ResourcePublishedGeneration(
            "generation_2",
            "run",
            None,
            "v1",
            datetime.now(UTC),
            tuple(
                DatasetSummary(
                    AnalyticalGrain(ref.grain),
                    "v1",
                    ref.row_count,
                    coverage[ref.grain].first_period,
                    coverage[ref.grain].last_period,
                    ref.object.key,
                    ref.object.sha256,
                    ref.object.byte_count,
                )
                for ref in receipt.resources
            ),
        )
        self.sessions = 0

    def objects(self):
        self.sessions += 1
        return S3ResourceStore(
            self.client, "test-bucket", "connector/", ARTIFACT_BOUNDS
        )

    def cache(self, tmp_path, bounds=CACHE):
        return VerifiedResourceCache(
            tmp_path / "cache",
            ResourceReadSessions(self.objects),
            ARTIFACT_BOUNDS,
            bounds,
        )

    def changed(self, grain, **changes):
        return replace(
            self.generation,
            datasets=tuple(
                replace(item, **changes) if item.grain == grain else item
                for item in self.generation.datasets
            ),
        )


@pytest.fixture
def published(tmp_path):
    return Published(tmp_path)


def dataset_for(grain):
    return next(item for item in PUBLIC_DATASETS if item.grain == grain.value)


def test_cold_read_downloads_only_each_described_file_without_metadata_lookup(
    tmp_path, published
):
    reader = published.cache(tmp_path)
    pins = {}
    for grain in AnalyticalGrain:
        pins[grain] = reader.prepare(published.generation, dataset_for(grain))
    assert published.client.calls == [
        ("get", item.object_key) for item in published.generation.datasets
    ]
    assert published.sessions == 3
    for item in published.generation.datasets:
        (file,) = pins[item.grain].files
        assert (file.sha256, file.byte_count, file.rows) == (
            item.sha256,
            item.byte_count,
            item.rows,
        )
        path = Path(file.path)
        assert path.name == f"{item.sha256}-{FILES[item.grain]}.parquet"
        assert stat.S_IMODE(path.stat().st_mode) == 0o400
        # The unified private physical schema is retained on disk, never reprojected.
        assert pq.read_schema(path).equals(
            schema_for("resource", item.grain.value), check_metadata=True
        )
    assert len(list((tmp_path / "cache").iterdir())) == 3
    for pin in pins.values():
        pin.close()


def test_warm_pin_does_not_reread_the_object(tmp_path, published):
    reader = published.cache(tmp_path)
    first = reader.prepare(published.generation, dataset_for(AnalyticalGrain.NATIONAL))
    second = reader.prepare(published.generation, dataset_for(AnalyticalGrain.NATIONAL))
    assert len(published.client.calls) == 1
    assert first.files == second.files
    first.close()
    second.close()


def test_views_expose_only_public_columns_for_every_grain(tmp_path, published):
    reader = published.cache(tmp_path)
    pins = [
        (dataset, reader.prepare(published.generation, dataset))
        for dataset in PUBLIC_DATASETS
    ]
    connection = open_restricted(
        EXECUTION, [(dataset.id, dataset, pin.files) for dataset, pin in pins]
    )
    try:
        for dataset, pin in pins:
            result = connection.execute(f'SELECT * FROM "{dataset.id}" ORDER BY period')
            assert [c[0] for c in result.description] == [
                c.name for c in dataset.columns
            ]
            rows = result.fetchall()
            assert len(rows) == len(DAYS) == pin.files[0].rows
            assert [row[0] for row in rows] == [date.fromisoformat(d) for d in DAYS]
            for private in ("origin", "identity", "capacity_source", "share_numerator"):
                with pytest.raises(duckdb.BinderException):
                    connection.execute(f'SELECT "{private}" FROM "{dataset.id}"')
        with pytest.raises(duckdb.Error):
            connection.execute("SELECT * FROM read_parquet('/etc/passwd')")
    finally:
        connection.close()
        for _, pin in pins:
            pin.close()


@pytest.mark.parametrize(
    "mutation",
    [
        {"sha256": "f" * 64},
        {"byte_count": 1},
        {"rows": 1},
        {"start": date(2026, 8, 1)},
        {"end": date(2026, 9, 2)},
        {
            "schema_version": "v1",
            "object_key": "connector/generations/x/national.parquet",
        },
    ],
)
def test_wrong_descriptor_is_unavailable_and_leaves_no_cache_file(
    tmp_path, published, mutation
):
    reader = published.cache(tmp_path)
    wrong = published.changed(AnalyticalGrain.NATIONAL, **mutation)
    with pytest.raises((DataUnavailableError, AnalyticalResourceError)):
        reader.prepare(wrong, dataset_for(AnalyticalGrain.NATIONAL))
    assert not list((tmp_path / "cache").iterdir())
    assert not reader._entries


@pytest.mark.parametrize("fault", ["corrupt", "missing", "short"])
def test_unverifiable_object_is_unavailable_without_fallback(
    tmp_path, published, fault
):
    item = next(
        i for i in published.generation.datasets if i.grain is AnalyticalGrain.FACILITY
    )
    if fault == "missing":
        del published.client.objects[item.object_key]
    elif fault == "corrupt":
        data = published.client.objects[item.object_key]
        published.client.objects[item.object_key] = b"X" * len(data)
    else:
        published.client.length_transform = lambda key, data: len(data) - 1
    reader = published.cache(tmp_path)
    with pytest.raises(DataUnavailableError):
        reader.prepare(published.generation, dataset_for(AnalyticalGrain.FACILITY))
    assert not list((tmp_path / "cache").iterdir())
    assert not reader._entries


def test_wrong_physical_schema_is_unavailable(tmp_path, published):
    """An object with the described hash but a public-only layout is refused."""
    item = next(
        i for i in published.generation.datasets if i.grain is AnalyticalGrain.NATIONAL
    )
    table = pq.read_table(
        io.BytesIO(published.client.objects[item.object_key]),
        columns=[c.name for c in dataset_for(AnalyticalGrain.NATIONAL).columns],
    )
    sink = io.BytesIO()
    pq.write_table(table, sink)
    data = sink.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    key = item.object_key
    published.client.objects[key] = data
    wrong = published.changed(
        AnalyticalGrain.NATIONAL, sha256=digest, byte_count=len(data)
    )
    reader = published.cache(tmp_path)
    with pytest.raises(DataUnavailableError):
        reader.prepare(wrong, dataset_for(AnalyticalGrain.NATIONAL))
    assert not list((tmp_path / "cache").iterdir())


def test_cache_budgets_are_enforced_before_download(tmp_path, published):
    reader = published.cache(tmp_path, replace(CACHE, rows=1))
    with pytest.raises(AnalyticalResourceError):
        reader.prepare(published.generation, dataset_for(AnalyticalGrain.NATIONAL))
    small = published.cache(tmp_path / "small", replace(CACHE, bytes=1))
    with pytest.raises(AnalyticalResourceError):
        small.prepare(published.generation, dataset_for(AnalyticalGrain.NATIONAL))
    assert published.client.calls == []


def test_dataset_and_generation_identity_are_checked_before_download(
    tmp_path, published
):
    reader = published.cache(tmp_path)
    with pytest.raises(DataUnavailableError):
        reader.prepare(
            replace(published.generation, id="other"),
            dataset_for(AnalyticalGrain.NATIONAL),
        )
    with pytest.raises(DataUnavailableError):
        reader.prepare(
            published.generation,
            PUBLIC_DATASETS[0].__class__(
                "other", "national", "National", PUBLIC_DATASETS[0].columns
            ),
        )
    assert published.client.calls == []


def test_pinned_file_survives_a_full_cache_and_is_evicted_after_release(
    tmp_path, published
):
    reader = published.cache(tmp_path, replace(CACHE, files=1))
    first = reader.prepare(published.generation, PUBLIC_DATASETS[0])
    with pytest.raises(AnalyticalResourceError):
        reader.prepare(published.generation, PUBLIC_DATASETS[1])
    assert all(Path(file.path).exists() for file in first.files)
    first.close()
    reader.prepare(published.generation, PUBLIC_DATASETS[1]).close()
    assert not any(Path(file.path).exists() for file in first.files)


def test_prior_generation_pin_survives_a_newer_generation(tmp_path, published):
    reader = published.cache(tmp_path)
    prior = reader.prepare(published.generation, PUBLIC_DATASETS[0])
    # Another generation with different bytes is a separate pinned cache object.
    item = published.generation.datasets[0]
    other = replace(
        published.generation,
        id="generation_3",
        datasets=tuple(
            replace(
                d,
                object_key=d.object_key.replace("generation_2", "generation_3"),
            )
            for d in published.generation.datasets
        ),
    )
    for d in other.datasets:
        published.client.objects[d.object_key] = published.client.objects[
            d.object_key.replace("generation_3", "generation_2")
        ]
    current = reader.prepare(other, PUBLIC_DATASETS[0])
    assert prior.files == current.files  # identical verified bytes are shared
    prior.close()
    assert all(Path(file.path).exists() for file in current.files)
    current.close()
    assert item.sha256 in prior.files[0].path


def test_preparation_deadline_and_closed_cache(tmp_path, published):
    reader = published.cache(tmp_path, replace(CACHE, preparation_seconds=1))
    ticks = iter([0.0, 5.0, 10.0, 15.0, 20.0, 25.0] + [30.0] * 100)
    with patch(
        "outage_explorer.infrastructure.local_cache.modeled.monotonic",
        lambda: next(ticks),
    ):
        with pytest.raises(AnalyticalResourceError):
            reader.prepare(published.generation, PUBLIC_DATASETS[0])
    assert not list((tmp_path / "cache").iterdir())
    reader.close()
    with pytest.raises(DataUnavailableError):
        reader.prepare(published.generation, PUBLIC_DATASETS[0])


def test_unified_schema_checking_rejects_foreign_files(tmp_path, published):
    reader = published.cache(tmp_path)
    pin = reader.prepare(published.generation, PUBLIC_DATASETS[1])
    file = pin.files[0]
    # The facilities file must not be accepted as another grain's dataset.
    with pytest.raises(DataUnavailableError):
        open_restricted(EXECUTION, [("national", PUBLIC_DATASETS[0], pin.files)])
    # Local replacement after pinning is detected by identity verification.
    path = Path(file.path)
    path.chmod(0o600)
    path.write_bytes(b"replaced")
    with pytest.raises(DataUnavailableError):
        reader.prepare(published.generation, PUBLIC_DATASETS[1])
