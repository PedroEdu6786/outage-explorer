"""Owned ephemeral results, reservation contention and autonomous real-file cleanup."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import psycopg
import pytest

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    AnalyticalTimeoutError,
    ForbiddenError,
    InvalidRequestError,
    QueryExpiredError,
    QueryUnavailableError,
    ResultCapacityError,
    RuntimeUnavailableError,
    UnauthenticatedError,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.bootstrap import build_query_result_lifecycle
from outage_explorer.domain.access import Role
from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import retain_result
from outage_explorer.infrastructure.query_results.store import (
    BoundedQueryResults,
    ResultBounds,
)
from outage_explorer.infrastructure.sql_validation.inspection import SqlRejected
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from tests.integration import test_query_results as sequences
from tests.integration.test_catalog_preview import ENCODING, EXECUTION, Clock

queries = sequences.queries
browsing = sequences.browsing
system = sequences.system
database = sequences.database
BOUNDS = sequences.BOUNDS


def output():
    retained = retain_result(
        (Column("n", ValueType("integer")),), [(1,), (2,)], ENCODING
    )
    return QueryOutput(
        retained.document, retained.retained_row_count, retained.truncation_reason
    )


def complete(store, owner="user"):
    reservation = store.reserve(owner)
    try:
        return reservation.complete(output(), frozenset(), None, 100)
    finally:
        reservation.close()


@pytest.mark.parametrize(
    "page,size", [(0, None), (-1, None), (True, None), (1, 0), (1, 501), (1, True)]
)
def test_invalid_pages_before_engine(queries, system, page, size):
    with pytest.raises(InvalidRequestError):
        queries[0].execute(
            system[2][Role.VIEWER],
            "SELECT 1",
            page=page,
            page_size=100 if size is None else size,
        )
    assert not queries[3].calls


def test_fresh_roles_foreign_ids_logout_before_payload(queries, system, database):
    service, _, _, runtime, _ = queries
    token = system[2][Role.ANALYST]
    result = service.execute(token, "SELECT * FROM facilities")
    with pytest.raises(QueryUnavailableError):
        service.page(system[2][Role.ADMIN], result["query_id"])
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE users SET role_code='viewer' WHERE id=%s",
            (system[3][Role.ANALYST].id,),
        )
    with pytest.raises(ForbiddenError):
        service.page(token, result["query_id"])
    system[1]._access.logout(token)
    with pytest.raises(UnauthenticatedError):
        service.page(token, result["query_id"])
    assert len(runtime.calls) == 1


@pytest.mark.parametrize(
    "sql,error",
    [
        ("SELECT * FROM facilities", ForbiddenError),
        ("SELECT * FROM generators", ForbiddenError),
        ("SELECT * FROM national JOIN facilities USING(period)", ForbiddenError),
        ("DROP TABLE national", SqlRejected),
        ("SELECT * FROM read_csv('/tmp/private')", SqlRejected),
        ("SELECT * FROM unknown", SqlRejected),
    ],
)
def test_denied_and_external_references_before_inputs(queries, system, sql, error):
    service = queries[0]
    inputs = service._inputs
    service._inputs = Mock()
    with pytest.raises(error):
        service.execute(system[2][Role.VIEWER], sql)
    service._inputs.prepare.assert_not_called()
    service._inputs = inputs
    assert not queries[3].calls


def test_fixed_completion_expiry_and_unavailable_after_loss(queries, system):
    service, store, clock, runtime, _ = queries
    original = runtime.query

    def delayed(request, bounds, deadline):
        clock.value += timedelta(seconds=123)
        return original(request, bounds, deadline)

    runtime.query = delayed
    token = system[2][Role.VIEWER]
    result = service.execute(token, "SELECT 1")
    identity = store._records[result["query_id"]].identity
    assert identity.completed_at == clock.now()
    assert identity.expires_at == clock.now() + timedelta(minutes=15)
    clock.value += timedelta(seconds=899)
    assert service.page(token, identity.id)["expires_at"] == result["expires_at"]
    clock.value += timedelta(seconds=1)
    with pytest.raises(QueryExpiredError):
        service.page(token, identity.id)
    store.cleanup()
    with pytest.raises(QueryUnavailableError):
        service.page(token, identity.id)
    assert len(runtime.calls) == 1


def test_generation_republication_does_not_execute_or_download(queries, system):
    service, _, _, runtime, _ = queries
    token = system[2][Role.ANALYST]
    result = service.execute(
        token, "SELECT generator FROM generators ORDER BY generator", page_size=100
    )
    service._publications = Mock()
    service._inputs = Mock()
    assert (
        service.page(token, result["query_id"], page=2)["generation_id"]
        == result["generation_id"]
    )
    service._publications.active_generation.assert_not_called()
    service._inputs.prepare.assert_not_called()
    assert len(runtime.calls) == 1


def test_reservations_count_inflight_release_and_never_evict(tmp_path):
    clock = Clock()
    store = BoundedQueryResults(
        tmp_path / "spool",
        clock,
        ResultBounds(1, 2, 2 * BOUNDS.reservation_bytes, BOUNDS.metadata_bytes),
    )
    store.start()
    pending = store.reserve("a")
    with pytest.raises(ResultCapacityError) as denied:
        store.reserve("a")
    assert denied.value.per_user
    identity = complete(store, "b")
    with pytest.raises(ResultCapacityError) as global_denied:
        store.reserve("c")
    assert not global_denied.value.per_user
    assert len(store._records) == 1
    pending.close()
    replacement = store.reserve("c")
    replacement.close()
    reader = store.acquire(identity.id, "b")
    assert reader.page(1)["rows"] == [["1"], ["2"]]
    reader.close()
    store.close()


def test_storage_bytes_reserve_worst_case(tmp_path):
    store = BoundedQueryResults(
        tmp_path / "spool",
        Clock(),
        ResultBounds(3, 10, BOUNDS.reservation_bytes, BOUNDS.metadata_bytes),
    )
    store.start()
    complete(store)
    with pytest.raises(ResultCapacityError) as caught:
        store.reserve("other")
    assert not caught.value.per_user
    store.close()


def test_active_readers_survive_expiry_cleanup_then_release(tmp_path):
    clock = Clock()
    store = BoundedQueryResults(tmp_path / "spool", clock, BOUNDS)
    store.start()
    identity = complete(store)
    reader = store.acquire(identity.id, "user")
    path = store._records[identity.id].path
    clock.value += timedelta(minutes=15)
    with ThreadPoolExecutor(2) as executor:
        assert executor.submit(store.cleanup).result() == 0
        assert executor.submit(reader.page, 1).result()["rows"] == [["1"], ["2"]]
    with pytest.raises(QueryExpiredError):
        store.acquire(identity.id, "user")
    assert path.exists()
    with pytest.raises(ValueError, match="Active"):
        store.close()
    reader.close()
    assert store.cleanup() == 1 and not path.exists()
    store.close()


def test_autonomous_cleanup_without_next_request_and_inert_bootstrap(tmp_path):
    root = tmp_path / "spool"
    store, lifecycle = build_query_result_lifecycle(
        root, BOUNDS, cleanup_interval_seconds=0.01
    )
    assert not root.exists() and lifecycle._thread is None
    clock = Clock()
    store._clock = clock
    lifecycle.start()
    identity = complete(store)
    path = store._records[identity.id].path
    clock.value += timedelta(minutes=15)
    deadline = __import__("time").monotonic() + 3
    while path.exists() and __import__("time").monotonic() < deadline:
        Event().wait(0.02)
    assert not path.exists() and not store._records
    lifecycle.close()


def test_dead_process_orphans_live_owner_and_durable_files(tmp_path):
    root = tmp_path / "spool"
    code = """import sys
from pathlib import Path
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.query_results.store import BoundedQueryResults, ResultBounds
store=BoundedQueryResults(Path(sys.argv[1]),SystemClock(),ResultBounds(3,10,12000000,131072))
store.start()
(store._directory / ('a'*32+'.json')).write_bytes(b'bounded abandoned result')
(store._directory / 'durable.parquet').write_bytes(b'preserve unknown data')
"""
    subprocess.run(
        [sys.executable, "-c", code, str(root)],
        check=True,
        env={"PYTHONPATH": str(Path("src").resolve())},
    )
    dead = next(root.iterdir())
    live = BoundedQueryResults(root, Clock(), BOUNDS)
    live.start()
    identity = complete(live)
    current = BoundedQueryResults(root, Clock(), BOUNDS)
    current.start()
    assert current.cleanup() == 1
    assert (dead / "durable.parquet").read_bytes() == b"preserve unknown data"
    assert live._records[identity.id].path.exists()
    current.close()
    live.close()


def test_topology_rejected_and_no_fork_reuse(tmp_path, monkeypatch):
    store = BoundedQueryResults(tmp_path / "spool", Clock(), BOUNDS)
    with pytest.raises(ValueError):
        store.start(serving_processes=2)
    assert not (tmp_path / "spool").exists()
    store.start()
    with monkeypatch.context() as patch:
        patch.setattr(os, "getpid", lambda: store._pid + 1)
        with pytest.raises(QueryUnavailableError):
            store.reserve("a")
    store.close()


def test_busy_admission_before_inputs_and_reservation_release(queries, system):
    service, store, _, runtime, launcher = queries
    held = launcher.reserve()
    service._inputs = Mock()
    try:
        with pytest.raises(AnalyticalBusyError):
            service.execute(system[2][Role.ANALYST], "SELECT * FROM facilities")
        service._inputs.prepare.assert_not_called()
        assert not runtime.calls and not store._pending
    finally:
        held.close()
    assert service.execute(system[2][Role.VIEWER], "SELECT 1")["rows"] == [["1"]]


def test_runtime_disabled_failure_cleanup_and_timeout_isolation(
    queries, system, monkeypatch
):
    service, store, _, runtime, launcher = queries
    service._execution = VerifiedLauncher(EXECUTION)
    with pytest.raises(RuntimeUnavailableError):
        service.execute(system[2][Role.VIEWER], "SELECT 1")
    assert not store._pending
    service._execution = launcher
    original = runtime.query
    runtime.query = Mock(side_effect=AnalyticalTimeoutError("Execution expired"))
    with pytest.raises(AnalyticalTimeoutError):
        service.execute(system[2][Role.VIEWER], "SELECT 1")
    assert not store._pending and not store._records
    runtime.query = original
    assert service.execute(system[2][Role.VIEWER], "SELECT 2")["rows"] == [["2"]]


def test_missing_tampered_spool_unavailable_without_execution(queries, system):
    service, store, _, runtime, _ = queries
    token = system[2][Role.VIEWER]
    result = service.execute(token, "SELECT 1")
    path = store._records[result["query_id"]].path
    path.write_bytes(b"x")
    with pytest.raises(QueryUnavailableError):
        service.page(token, result["query_id"])
    path.unlink()
    with pytest.raises(QueryUnavailableError):
        service.page(token, result["query_id"])
    assert len(runtime.calls) == 1
