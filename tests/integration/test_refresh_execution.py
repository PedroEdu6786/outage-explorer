"""Admitted work with real PostgreSQL/Parquet and controlled HTTP/S3."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from outage_explorer.application.ports.artifacts import ArtifactLimitError
from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.bootstrap import build_http_app, build_refresh_worker
from outage_explorer.domain.access import Role
from outage_explorer.domain.publication import RunStatus
from tests.integration import test_data_api_postgresql as coordination
from tests.integration.test_connector_cli import Wire, row
from tests.integration.test_s3_artifacts import ControlledS3, failure

database = coordination.database


@pytest.fixture
def system(database):
    from outage_explorer.application.services.refresh import RefreshService
    from outage_explorer.infrastructure.postgresql.publication import (
        PostgresqlResourcePublicationStore,
    )

    for legacy_system in coordination.system.__wrapped__(database):
        _, service, tokens, users, pool = legacy_system
        store = PostgresqlResourcePublicationStore(pool)
        refresh = RefreshService(
            service._access, store, lambda: coordination.CONFIG, service._security
        )
        yield store, refresh, tokens, users, pool


class RefreshS3(ControlledS3):
    def head_object(self, **kwargs):
        key = kwargs["Key"]
        self.calls.append(("head", key))
        if key not in self.objects:
            raise failure("NoSuchKey")
        return {"ContentLength": len(self.objects[key])}


def composition(database, root, wire=None, client=None):
    return build_refresh_worker(
        environment={
            "OUTAGE_ACCESS_DATABASE_DSN": database,
            "OUTAGE_REFRESH_STAGING": str(root),
            "OUTAGE_S3_BUCKET": "test-bucket",
            "OUTAGE_S3_PREFIX": "connector/",
            "AWS_REGION": "us-east-1",
            "EIA_API_KEY": "synthetic-only-secret",
        },
        transport=Wire() if wire is None else wire,
        client=RefreshS3() if client is None else client,
    )


def admit(system, key="a" * 16):
    return system[1].admit(system[2][Role.ADMIN], key, {})


def execute(system, database, root, rows=None, client=None, key="a" * 16, **options):
    run = admit(system, key)
    process = composition(database, root, Wire(rows, **options), client)
    try:
        result = process.tick()
        assert result.id == run.id
        return result
    finally:
        process.close()


def test_all_grains_durably_publish_with_verified_real_artifacts(
    system, database, tmp_path
):
    client = RefreshS3()
    result = execute(system, database, tmp_path, client=client)
    assert result.status is RunStatus.SUCCEEDED
    active = system[0].active_generation()
    assert active.run_id == result.id
    assert len(active.datasets) == 3
    assert all(item.rows == 1 for item in active.datasets)
    assert any(operation == "put" for operation, _ in client.calls)
    assert any(operation == "get" for operation, _ in client.calls)
    assert len(json.loads(result.quality_json)["datasets"]) == 3


def test_browser_expiry_and_api_restart_do_not_own_admitted_work(
    system, database, tmp_path
):
    entered, released = Event(), Event()

    class BlockedWire(Wire):
        def handle_request(self, request):
            entered.set()
            assert released.wait(10)
            return super().handle_request(request)

    run = admit(system)
    assert run.status is RunStatus.ACCEPTED
    process = composition(database, tmp_path, BlockedWire())
    try:
        with ThreadPoolExecutor() as pool:
            future = pool.submit(process.tick)
            assert entered.wait(5)
            assert system[0].get_run(run.id).status is RunStatus.RUNNING
            # The initiator's browser/session can vanish and API factories restart.
            system[1]._access.logout(system[2][Role.ADMIN])
            with patch.dict("os.environ", {}, clear=True):
                for _ in range(2):
                    assert (
                        build_http_app().test_client().get("/health").status_code == 200
                    )
            system[0].recover(run.id)  # Healthy lease cannot be reclaimed.
            released.set()
            assert future.result(timeout=10).status is RunStatus.SUCCEEDED
    finally:
        released.set()
        process.close()


def test_frozen_admission_dates_and_limits_ignore_worker_configuration(
    system, database, tmp_path
):
    run = admit(system)
    process = composition(database, tmp_path)
    try:
        with patch.dict("os.environ", {"OUTAGE_REFRESH_START_DATE": "2020-01-01"}):
            result = process.tick()
        assert result.configuration == run.configuration
        assert result.status is RunStatus.SUCCEEDED
    finally:
        process.close()


def test_subsequent_refresh_beyond_183_days_uses_frozen_source_model_span(
    system, database, tmp_path, monkeypatch
):
    from datetime import UTC, datetime

    from outage_explorer.bootstrap import build_data_services
    from outage_explorer.infrastructure.clock import SystemClock

    client = RefreshS3()
    execute(system, database, tmp_path, client=client)
    store, service, tokens, _, _ = system
    monkeypatch.setattr(
        SystemClock, "now", lambda self: datetime(2026, 10, 7, tzinfo=UTC)
    )
    refresh = build_data_services(
        service._access,
        store,
        service._security,
        {"OUTAGE_REFRESH_START_DATE": "2026-04-02"},
    ).refresh
    run = refresh.admit(tokens[Role.ADMIN], "long-interval-key", {})
    assert run.configuration.max_interval_days == 189
    wire = Wire(
        {
            grain: [row(grain, period="2026-10-07")]
            for grain in ("national", "facility", "generator")
        }
    )
    process = composition(database, tmp_path, wire, client)
    try:
        result = process.tick()
        assert result.status is RunStatus.SUCCEEDED
        assert result.configuration == run.configuration
        assert store.active_generation().run_id == run.id
        requests = [r for r in wire.calls if r.url.path.endswith("/data/")]
        assert len({r.url.path for r in requests}) == 3
        assert all(r.url.params["start"] == "2026-04-02" for r in requests)
        assert all(r.url.params["end"] == "2026-10-07" for r in requests)
    finally:
        process.close()


def test_all_excluded_retains_pointer_with_overlapping_reasons(
    system, database, tmp_path
):
    client = RefreshS3()
    initial = execute(system, database, tmp_path, client=client)
    before = system[0].active_generation()
    calls = len(client.calls)
    rows = {
        grain: [row(grain, capacity="bad", outage="bad")]
        for grain in ("national", "facility", "generator")
    }
    retained = execute(system, database, tmp_path, rows, client, key="b" * 16)
    assert retained.status is RunStatus.RETAINED
    assert retained.no_publication_reason == "all_incoming_rows_excluded"
    assert system[0].active_generation() == before
    assert retained.generation_id is None
    assert not any(operation == "put" for operation, _ in client.calls[calls:])
    for dataset in json.loads(retained.quality_json)["datasets"]:
        assert dataset["received"] == dataset["excluded"] == 1
        assert sum(dataset["exclusion_reasons"].values()) == 2
        assert dataset["retained_invalid"] == 1
    assert system[0].generation_for_run(initial.id) == before


def test_partial_exclusion_invalid_absent_and_duplicate_conservation(
    system, database, tmp_path
):
    client = RefreshS3()
    original = {
        grain: [row(grain, period=f"2026-09-0{day}") for day in (1, 2, 3)]
        for grain in ("national", "facility", "generator")
    }
    first = execute(system, database, tmp_path, original, client)
    pinned = system[0].active_generation()
    rows = {
        "national": [
            row("national", capacity="bad"),
            row("national", period="2026-09-03", outage="2"),
            row("national", period="2026-09-03", outage="2"),
        ],
        "facility": [row("facility", capacity="bad")],
        "generator": [row("generator", period="2026-09-03", outage="2")],
    }
    updated = execute(system, database, tmp_path, rows, client, key="b" * 16)
    assert updated.status is RunStatus.SUCCEEDED
    assert (
        system[0].generation_for_run(first.id) == pinned
    )  # Immutable readers retain their base.
    assert system[0].active_generation().base_generation_id == pinned.id
    for dataset in json.loads(updated.quality_json)["datasets"]:
        assert dataset["received"] == sum(
            dataset[key] for key in ("selected", "excluded", "duplicate", "superseded")
        )
        assert dataset["output"] == 3
    national, facility, _ = json.loads(updated.quality_json)["datasets"]
    assert (
        national["duplicate"] == 1
        and national["retained_invalid"] == 1
        and national["retained_absent"] == 1
    )
    assert facility["excluded"] == 1 and facility["retained_absent"] == 2


@pytest.mark.parametrize(
    "kind",
    ["empty", "excluded", "failed_source", "corrupt_s3", "missing_s3", "resource"],
)
def test_failure_never_publishes_partial_initial_generation(
    system, database, tmp_path, kind
):
    rows = {grain: [row(grain)] for grain in ("national", "facility", "generator")}
    client = RefreshS3()
    options = {}
    if kind == "empty":
        rows["facility"] = []
    elif kind == "excluded":
        rows["facility"] = [row("facility", capacity="bad")]
    elif kind == "failed_source":
        options["failure"] = ("facility", 0)
    elif kind == "corrupt_s3":
        client.read_transform = lambda key, data: b"x" + data[1:]
    elif kind == "missing_s3":
        client.get_faults = [failure("NoSuchKey")]
    admit(system)
    wire = Wire(rows, **options)
    process = composition(database, tmp_path, wire, client)
    try:
        if kind == "resource":
            with patch(
                "outage_explorer.infrastructure.connector_workers.BoundedConnectorWorkers.check",
                side_effect=ArtifactLimitError("secret"),
            ):
                result = process.tick()
        else:
            result = process.tick()
        assert result.status is RunStatus.FAILED
        assert result.failure in {
            "unusable_input",
            "retrieval",
            "artifact_integrity",
            "resource",
        }
        assert system[0].active_generation() is None
        assert "secret" not in (result.quality_json or "")
    finally:
        process.close()


def _api_lifetime():
    # Independent API composition/teardown, with no refresh runtime ownership.
    with patch.dict("os.environ", {}, clear=True):
        assert build_http_app().test_client().get("/health").status_code == 200


def _worker_lifetime(dsn, root, entered, released):
    class ProcessWire(Wire):
        def handle_request(self, request):
            entered.set()
            assert released.wait(20)
            return super().handle_request(request)

    process = composition(dsn, root, ProcessWire())
    worker = process.tick.__self__
    from outage_explorer.infrastructure.refresh_worker import RenewableRefreshLease

    worker.lease_seconds = 2
    worker.lease = RenewableRefreshLease(worker.store, seconds=2, renew_seconds=0.1)
    try:
        assert process.tick().status is RunStatus.SUCCEEDED
    finally:
        process.close()


def test_independent_worker_process_survives_api_process_restarts(
    system, database, tmp_path
):
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    entered, released = context.Event(), context.Event()
    run = admit(system)
    worker = context.Process(
        target=_worker_lifetime, args=(database, str(tmp_path), entered, released)
    )
    worker.start()
    try:
        assert entered.wait(10)
        assert system[0].get_run(run.id).status is RunStatus.RUNNING
        system[1]._access.logout(system[2][Role.ADMIN])
        for _ in range(2):
            api = context.Process(target=_api_lifetime)
            api.start()
            api.join(10)
            assert api.exitcode == 0
        assert worker.is_alive()
        assert RefreshRecovery(system[0]).execute(run.id).status is RunStatus.RUNNING
        released.set()
        worker.join(15)
        assert worker.exitcode == 0
        assert system[0].get_run(run.id).status is RunStatus.SUCCEEDED
    finally:
        released.set()
        worker.join(5)
        if worker.is_alive():
            worker.terminate()
            worker.join(5)


def test_failed_refresh_preserves_prior_and_missing_base_fails_before_source(
    system, database, tmp_path
):
    client = RefreshS3()
    first = execute(system, database, tmp_path, client=client)
    active = system[0].active_generation()
    wire = Wire(failure=("facility", 0))
    run = admit(system, "b" * 16)
    process = composition(database, tmp_path, wire, client)
    try:
        assert process.tick().status is RunStatus.FAILED
        assert system[0].active_generation() == active
        assert system[0].generation_for_run(first.id) == active
        assert system[0].generation_for_run(run.id) is None
    finally:
        process.close()
    del client.objects[active.datasets[0].object_key]
    wire = Wire()
    admit(system, "c" * 16)
    process = composition(database, tmp_path, wire, client)
    try:
        assert process.tick().status is RunStatus.FAILED
        assert not wire.calls
        assert system[0].active_generation() == active
    finally:
        process.close()


def test_unmeasured_quality_counts_remain_null_and_worker_shutdown_is_explicit(
    system, database, tmp_path
):
    admit(system)
    process = composition(database, tmp_path, Wire(failure=("national", 0)))
    try:
        result = process.tick()
        datasets = json.loads(result.quality_json)["datasets"]
        assert all(
            item["selected"] is None and item["excluded"] is None for item in datasets
        )
        assert result.failure == "retrieval"
    finally:
        process.close()
        process.close()
    assert process.closed


def test_s3_metadata_is_bounded_and_not_a_verified_receipt():
    from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
    from tests.integration.test_connector_cli import ARTIFACT

    client = RefreshS3()
    client.head_object = lambda **kwargs: {"ContentLength": ARTIFACT.file_bytes + 1}
    store = S3ArtifactStore(client, "test-bucket", "connector/", ARTIFACT)
    with pytest.raises(ArtifactLimitError):
        store.reference("a" * 64, "a" * 64)


def test_worker_construction_starts_no_io_or_jobs(tmp_path):
    with (
        patch("boto3.Session", side_effect=AssertionError("SDK constructed")),
        patch(
            "httpx.HTTPTransport", side_effect=AssertionError("Transport constructed")
        ),
        patch("psycopg.connect", side_effect=AssertionError("Database connected")),
        patch("threading.Thread.start", side_effect=AssertionError("Job started")),
    ):
        process = composition(
            "host=127.0.0.1 port=5432 dbname=postgres user=controlled", tmp_path
        )
        process.close()


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_frozen_transfer_workers_exact_descriptors_and_joined_staging_cleanup(
    system, database, tmp_path, workers
):
    import hashlib
    from dataclasses import replace
    from threading import enumerate as threads

    import psycopg

    system[1]._configuration = lambda: replace(coordination.CONFIG, s3_workers=workers)
    client = RefreshS3()
    result = execute(system, database, tmp_path, client=client)
    assert result.status is RunStatus.SUCCEEDED
    assert result.configuration.s3_workers == workers
    active = system[0].active_generation()
    expected = {
        f"connector/generations/{result.id}/{name}.parquet"
        for name in ("national", "facilities", "generators")
    }
    assert set(client.objects) == expected
    assert sorted(op for op, _ in client.calls) == ["get"] * 3 + ["put"] * 3
    for dataset in active.datasets:
        payload = client.objects[dataset.object_key]
        assert dataset.sha256 == hashlib.sha256(payload).hexdigest()
        assert dataset.byte_count == len(payload)
        assert dataset.rows == 1
    assert not (tmp_path / result.id).exists()
    assert not any(thread.name.startswith("connector_") for thread in threads())
    with psycopg.connect(database) as connection:
        record = connection.execute(
            "SELECT manifest_key, manifest_digest, datasets FROM published_generations WHERE id=%s",
            (result.id,),
        ).fetchone()
        quality = connection.execute(
            "SELECT quality_json FROM refresh_runs WHERE id=%s", (result.id,)
        ).fetchone()[0]
    assert record[:2] == (None, None)
    assert {dataset["object_key"] for dataset in record[2]} == expected
    assert quality == json.loads(result.quality_json)
    for summary in quality["datasets"]:
        assert (
            summary["received"],
            summary["selected"],
            summary["excluded"],
            summary["output"],
        ) == (1, 1, 0, 1)
        assert summary["exclusion_reasons"] == {}


@pytest.mark.parametrize(
    "fault", ["upload", "checksum", "deadline", "cancellation", "bounds"]
)
def test_transfer_failure_keeps_exact_previous_publication_and_all_workers_join(
    system, database, tmp_path, fault
):
    from threading import enumerate as threads

    from outage_explorer.infrastructure.s3.resources import S3ResourceStore

    client = RefreshS3()
    first = execute(system, database, tmp_path, client=client)
    before = system[0].active_generation()
    original = S3ResourceStore.put_verified

    def transfer(adapter, reference, chunks):
        if fault == "upload":
            raise failure("AccessDenied")
        if fault in ("deadline", "bounds"):
            raise ArtifactLimitError("controlled cap")
        if fault == "cancellation":
            adapter.cancelled.set()
        return original(adapter, reference, chunks)

    if fault == "checksum":
        client.read_transform = lambda key, data: (
            (b"x" + data[1:])
            if key.startswith("connector/generations/") and first.id not in key
            else data
        )
    with patch.object(S3ResourceStore, "put_verified", transfer):
        result = execute(system, database, tmp_path, client=client, key="d" * 16)
    assert result.status is RunStatus.FAILED
    assert system[0].active_generation() == before
    assert system[0].generation_for_run(result.id) is None
    assert not (tmp_path / result.id).exists()
    assert not any(thread.name.startswith("connector_") for thread in threads())


def test_narrow_refresh_carries_outside_interval_and_replaces_valid_values(
    system, database, tmp_path
):
    from dataclasses import replace
    from datetime import date
    from fractions import Fraction
    from io import BytesIO

    import pyarrow.parquet as pq

    from outage_explorer.infrastructure.parquet.schemas import modeled_from_record

    client = RefreshS3()
    values = {
        grain: [row(grain, period=f"2026-09-0{day}") for day in (1, 2, 3)]
        for grain in ("national", "facility", "generator")
    }
    execute(system, database, tmp_path, values, client)
    original = system[0].active_generation()
    system[1]._configuration = lambda: replace(
        coordination.CONFIG, start=date(2026, 9, 2), end=date(2026, 9, 2)
    )
    update = {grain: [row(grain, period="2026-09-02", outage="2")] for grain in values}
    result = execute(system, database, tmp_path, update, client, key="e" * 16)
    assert result.status is RunStatus.SUCCEEDED
    assert system[0].active_generation().base_generation_id == original.id
    for dataset in system[0].active_generation().datasets:
        rows = [
            modeled_from_record(record, dataset.grain.value)
            for record in pq.read_table(
                BytesIO(client.objects[dataset.object_key])
            ).to_pylist()
        ]
        assert [entry.result.percentage for entry in rows] == [
            Fraction(100, 3),
            Fraction(200, 3),
            Fraction(100, 3),
        ]
    for summary in json.loads(result.quality_json)["datasets"]:
        assert summary["carried_outside_interval"] == 2
        assert summary["output"] == 3
