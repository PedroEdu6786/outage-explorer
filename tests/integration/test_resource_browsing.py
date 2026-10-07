"""Authorized browsing over exact resource descriptors: real PostgreSQL/Parquet,
controlled S3 and engine subprocess. No OS isolation or cloud claims."""

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    DataUnavailableError,
    ForbiddenError,
    PreviewUnavailableError,
)
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.application.services.catalog import CatalogService
from outage_explorer.application.services.preview import PreviewService
from outage_explorer.application.services.queries import QueryService
from outage_explorer.application.services.refresh import RefreshService
from outage_explorer.application.services.resource_artifacts import (
    PersistResourceArtifacts,
)
from outage_explorer.domain.access import AnalyticalGrain, Role
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.local_cache.modeled import (
    ResourceReadSessions,
    VerifiedResourceCache,
)
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlResourcePublicationStore,
)
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.query_results.previews import (
    BoundedPreviewSequences,
)
from outage_explorer.infrastructure.query_results.store import BoundedQueryResults
from outage_explorer.infrastructure.s3.resources import S3ResourceStore
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from tests.integration import test_data_api_postgresql as coordination
from tests.integration.test_catalog_preview import (
    CACHE,
    ENCODING,
    EXECUTION,
    METADATA,
    Clock,
    ControlledRuntime,
)
from tests.integration.test_connector_cli import row
from tests.integration.test_connector_parquet import ARTIFACT_BOUNDS, BOUNDS
from tests.integration.test_query_results import BOUNDS as RESULT_BOUNDS
from tests.integration.test_query_results import QueryRuntime
from tests.integration.test_resource_candidates import build
from tests.integration.test_s3_artifacts import ControlledS3

database = coordination.database
system = coordination.system

IDENTIFIERS = ["001", "01", "1", "A", "Z", "a", "é", "😀"]
FILES = {"national": "national", "facility": "facilities", "generator": "generators"}


def values_for(national_outage="1"):
    return {
        "national": [
            row("national", period=day, outage=national_outage)
            for day in ("2026-09-01", "2026-09-02")
        ],
        "facility": [row("facility", facility=value) for value in IDENTIFIERS],
        "generator": [
            row("generator", generator=f"{value:04}") for value in range(503)
        ],
    }


class Durable:
    """Durable three-file generations in a controlled S3 client."""

    def __init__(self, tmp_path):
        self.root = tmp_path / "durable"
        self.local = LocalParquetStore(self.root, ARTIFACT_BOUNDS)
        self.client = ControlledS3()
        self.baseline = None
        self.sessions = 0

    def publish(self, system, values, key):
        store, service, tokens, users, pool = system
        generation_id = str(uuid4())
        candidate = build(
            self.local, generation=generation_id, values=values, prior=self.baseline
        )
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
            LocalConnectorEvidence(self.local, workers), remote, workers
        ).execute(candidate, BOUNDS)
        self.baseline = candidate.baseline
        coverage = {item.grain: item for item in candidate.summaries}
        publications = PostgresqlResourcePublicationStore(pool)
        refresh = RefreshService(
            service._access,
            publications,
            lambda: coordination.CONFIG,
            service._security,
        )
        run = refresh.admit(tokens[Role.ADMIN], key, {})
        base = publications.active_generation()
        published = ResourcePublishedGeneration(
            generation_id,
            run.id,
            None if base is None else base.id,
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
        publications.publish(publications.claim("worker", 60), published)
        return published

    def objects(self):
        self.sessions += 1
        return S3ResourceStore(
            self.client, "test-bucket", "connector/", ARTIFACT_BOUNDS
        )


@pytest.fixture
def browsing(system, database, tmp_path):
    durable = Durable(tmp_path)
    first = durable.publish(system, values_for(), "r1" * 8)
    publications = PostgresqlResourcePublicationStore(system[4])
    cache = VerifiedResourceCache(
        tmp_path / "cache",
        ResourceReadSessions(durable.objects),
        ARTIFACT_BOUNDS,
        CACHE,
    )
    runtime = ControlledRuntime()
    launcher = VerifiedLauncher(
        EXECUTION, runtime, evidence="controlled test injection only"
    )
    clock = Clock()
    sequences = BoundedPreviewSequences(
        clock, METADATA, b"synthetic-test-cursor-key-32-bytes!"
    )
    service = PreviewService(
        system[1]._access,
        publications,
        cache,
        launcher,
        sequences,
        PreviewEncoding(ENCODING),
        response_bytes=1024**2,
    )
    durable.client.calls.clear()
    yield service, cache, sequences, clock, runtime, durable, first, publications
    sequences.close()


def test_catalog_roles_and_public_columns_before_data(system, browsing):
    _, _, _, _, runtime, durable, first, publications = browsing
    for role in Role:
        catalog = CatalogService(system[1]._access, publications).list(system[2][role])
        assert [entry.dataset.id for entry in catalog] == (
            ["national"]
            if role is Role.VIEWER
            else ["national", "facilities", "generators"]
        )
        assert all(entry.generation_id == first.id for entry in catalog)
        assert all(
            "origin" not in [column.name for column in entry.dataset.columns]
            for entry in catalog
        )
    assert durable.client.calls == [] and not runtime.calls


def test_forbidden_dataset_is_denied_before_any_download(system, browsing):
    service, cache, _, _, runtime, durable, _, _ = browsing
    with pytest.raises(ForbiddenError):
        service.page(system[2][Role.VIEWER], "facilities")
    assert durable.client.calls == [] and not runtime.calls and not cache._entries


@pytest.mark.parametrize("grain", ["national", "facility", "generator"])
def test_cold_read_downloads_exactly_one_file_without_manifest_or_head(
    system, browsing, grain
):
    service, cache, _, _, runtime, durable, first, _ = browsing
    dataset = next(item for item in PUBLIC_DATASETS if item.grain == grain)
    page = service.page(system[2][Role.ADMIN], dataset.id, size=1)
    descriptor = next(i for i in first.datasets if i.grain.value == grain)
    assert durable.client.calls == [("get", descriptor.object_key)]
    # Warm reads and continuations never repeat the transfer.
    service.page(system[2][Role.ADMIN], dataset.id, cursor=page["next_cursor"])
    assert durable.client.calls == [("get", descriptor.object_key)]
    (file,) = runtime.calls[0].files
    # The private unified columns are on disk but never exposed.
    assert pq.read_schema(file.path).equals(
        schema_for("resource", grain), check_metadata=True
    )
    assert [column["name"] for column in page["columns"]] == [
        column.name for column in dataset.columns
    ]
    assert "origin" not in [column["name"] for column in page["columns"]]
    assert all(entry.pins == 1 for entry in cache._entries.values())


def test_binary_identifier_ties_and_exact_values_over_the_unified_file(
    system, browsing
):
    service = browsing[0]
    token = system[2][Role.ANALYST]
    first = service.page(token, "facilities", size=3)
    rows, current = list(first["rows"]), first
    while current["has_more"]:
        current = service.page(token, "facilities", cursor=current["next_cursor"])
        rows.extend(current["rows"])
    assert [values[4] for values in rows] == sorted(
        IDENTIFIERS, key=lambda s: s.encode("utf-8")
    )
    assert service.page(token, "facilities", cursor=first["page_cursor"]) == first
    national = service.page(system[2][Role.VIEWER], "national")
    columns = [column["name"] for column in national["columns"]]
    assert national["rows"][0][columns.index("reported_percentage")] == (
        "33.333333333333"
    )
    assert national["rows"][0][columns.index("calculated_percentage_rounded")] == (
        "33.33"
    )


def test_503_row_keyset_over_generators(system, browsing):
    service = browsing[0]
    page = service.page(system[2][Role.ADMIN], "generators", size=500)
    rows = list(page["rows"])
    while page["has_more"]:
        page = service.page(
            system[2][Role.ADMIN], "generators", cursor=page["next_cursor"]
        )
        rows.extend(page["rows"])
    assert [values[-1] for values in rows] == [f"{value:04}" for value in range(503)]


@pytest.mark.parametrize("fault", ["missing", "corrupt", "tampered-after-pin"])
def test_missing_or_corrupt_descriptor_object_is_unavailable(system, browsing, fault):
    service, cache, _, _, _, durable, first, _ = browsing
    token = system[2][Role.VIEWER]
    descriptor = next(i for i in first.datasets if i.grain.value == "national")
    if fault == "missing":
        del durable.client.objects[descriptor.object_key]
    elif fault == "corrupt":
        data = durable.client.objects[descriptor.object_key]
        durable.client.objects[descriptor.object_key] = b"X" * len(data)
    else:
        page = service.page(token, "national")
        path = Path(next(iter(cache._entries.values())).files[0].path)
        path.chmod(0o600)
        path.write_bytes(b"corrupted")
        with pytest.raises(DataUnavailableError):
            service.page(token, "national", cursor=page["page_cursor"])
        return
    with pytest.raises(DataUnavailableError):
        service.page(token, "national")
    assert not cache._entries
    assert not list(cache._root.glob("*.parquet"))


def test_busy_runtime_denies_before_download(system, browsing):
    service, _, _, _, _, durable, _, _ = browsing
    reservation = service._execution.reserve()
    try:
        with pytest.raises(AnalyticalBusyError):
            service.page(system[2][Role.VIEWER], "national")
        assert durable.client.calls == []
    finally:
        reservation.close()


def test_prior_generation_continuation_survives_newer_publication(system, browsing):
    service, cache, sequences, clock, _, durable, first, publications = browsing
    token = system[2][Role.VIEWER]
    page = service.page(token, "national", size=1)
    previous = service.page(token, "national", cursor=page["next_cursor"])
    second = durable.publish(system, values_for("2"), "r2" * 8)
    assert publications.active_generation() == second
    assert service.page(token, "national", cursor=page["page_cursor"]) == page
    assert service.page(token, "national", cursor=page["next_cursor"]) == previous
    fresh = service.page(token, "national", size=1)
    assert fresh["generation_id"] == second.id != page["generation_id"]
    assert fresh["rows"][0][2] == "2.000000000000"
    # Both generations hold distinct pinned files until the sequence expires.
    assert len(cache._entries) == 2
    assert all(entry.pins >= 1 for entry in cache._entries.values())
    clock.value += timedelta(seconds=60)
    sequences.cleanup()
    assert all(entry.pins == 0 for entry in cache._entries.values())
    with pytest.raises(PreviewUnavailableError):
        service.page(token, "national", cursor=page["page_cursor"])
    # The older generation remains immutable durable history.
    assert publications.generation_for_run(first.run_id) == first


@pytest.fixture
def queries(system, browsing, tmp_path):
    _, cache, _, clock, _, _, _, publications = browsing
    store = BoundedQueryResults(tmp_path / "results", clock, RESULT_BOUNDS)
    store.start()
    runtime = QueryRuntime()
    launcher = VerifiedLauncher(
        EXECUTION, runtime, evidence="synthetic controlled tests only"
    )
    service = QueryService(
        system[1]._access,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        publications,
        cache,
        launcher,
        store,
    )
    yield service, runtime
    store.close()


def test_single_execution_pagination_over_public_views(system, browsing, queries):
    service, runtime = queries
    token = system[2][Role.ANALYST]
    durable = browsing[5]
    sql = "SELECT generator AS x FROM generators ORDER BY x DESC LIMIT 301"
    first = service.execute(token, sql, page=1, page_size=100)
    pages = [service.page(token, first["query_id"], page=n) for n in range(1, 5)]
    assert sum(len(page["rows"]) for page in pages) == 301
    assert len(runtime.calls) == 1 and runtime.calls[0].sql == sql
    assert [name for name, _ in [(d.id, d) for d, _ in runtime.calls[0].relations]] == [
        "generators"
    ]
    assert len([call for call in durable.client.calls if call[0] == "get"]) == 1
    assert not any(call[0] == "head" for call in durable.client.calls)


def test_private_columns_are_not_queryable_and_viewer_is_denied(
    system, browsing, queries
):
    service, runtime = queries
    for private in ("origin", "identity", "capacity_source", "share_numerator"):
        with pytest.raises(SqlRejected) as rejected:
            service.execute(system[2][Role.ADMIN], f'SELECT "{private}" FROM national')
        assert rejected.value.code == "invalid_sql"
    durable = browsing[5]
    durable.client.calls.clear()
    with pytest.raises(ForbiddenError):
        service.execute(system[2][Role.VIEWER], "SELECT * FROM facilities")
    assert durable.client.calls == []
