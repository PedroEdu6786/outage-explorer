"""Real worker SQL errors through HTTP; mocked identity, no database or Docker."""

import subprocess
import sys
from unittest.mock import Mock

import pytest

from outage_explorer.application.services.queries import QueryService
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.infrastructure.query_results.store import BoundedQueryResults
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.decoding import WorkerTransport
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from tests.integration.test_catalog_preview import Clock
from tests.integration.test_query_results import BOUNDS

ORIGIN = "http://localhost:3000"

LOW_MEMORY_WORKER = """
import sys
from dataclasses import replace
from outage_explorer.bootstrap import build_query_worker
from outage_explorer.entrypoints.query_worker import run
from outage_explorer.infrastructure.duckdb import queries

# Controlled engine budget, deliberately below the product image profile.
# Keep real SQL execution and the complete v1 worker protocol.
execute_query = queries.execute_query
def bounded_query(request, bounds, encoding):
    return execute_query(request, replace(bounds, memory_bytes=1000000), encoding)
queries.execute_query = bounded_query
raise SystemExit(run(build_query_worker(), sys.stdin.buffer, sys.stdout.buffer))
"""


@pytest.fixture
def system(tmp_path):
    profile = RuntimeProfile(
        "sha256:" + "a" * 64, "unix:///tmp/docker.sock", "controlled", "test", "test"
    )
    transport = WorkerTransport(profile)

    def execute(request, bounds, deadline):
        result = subprocess.run(
            runtime.command,
            input=transport.request(request),
            capture_output=True,
            timeout=10,
            check=False,
        )
        assert result.stderr == b""
        return transport.decode(
            result.stdout, request=request, exit_code=result.returncode
        )

    runtime = Mock()
    runtime.command = [
        sys.executable,
        "-m",
        "outage_explorer.entrypoints.query_worker_startup",
    ]
    runtime.query.side_effect = execute
    launcher = VerifiedLauncher(
        profile.execution_bounds, runtime, evidence="controlled subprocess only"
    )
    store = BoundedQueryResults(tmp_path / "results", Clock(), BOUNDS)
    store.start()
    access, publications, inputs = Mock(), Mock(), Mock()
    access.authorize.return_value.principal.id = "owner"
    access.resolve.return_value.user.id = "owner"
    service = QueryService(
        access,
        DuckdbSqlInspector(max_sql_bytes=65536, max_nodes=10000, max_depth=64),
        publications,
        inputs,
        launcher,
        store,
    )
    app = create_app(
        Mock(),
        login_service=Mock(),
        access_service=access,
        auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
        data_services=DataServices(Mock(), Mock(), service, Mock(), Mock()),
    )
    client = app.test_client()
    client.set_cookie("outage_session", "token")
    yield client, store, launcher, runtime, access
    store.close()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT private_missing_column",
        "SELECT CAST('private-invalid-number' AS INTEGER)",
        "SELECT CAST(2147483647 AS INTEGER) + 1",
        "SELECT sqrt(-1)",
    ],
    ids=["binding", "conversion", "overflow", "invalid-function-input"],
)
def test_invalid_sql_is_400_without_result_or_retained_slot(system, sql):
    client, store, launcher, runtime, access = system
    headers = {"Origin": ORIGIN, "X-CSRF-Token": "csrf"}
    response = client.post("/api/query", json={"sql": sql}, headers=headers)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_sql"
    assert "private" not in response.text
    assert "query_id" not in response.json
    assert not store._pending and not store._records
    assert not launcher.active
    runtime.query.assert_called_once()
    runtime.terminate_and_reap.assert_called_once_with()
    access.validate_csrf.assert_called_once_with("token", "csrf")

    # A corrected request can immediately use the same slot and result capacity.
    corrected = client.post("/api/query", json={"sql": "SELECT 42"}, headers=headers)
    assert corrected.status_code == 200
    assert corrected.json["rows"] == [["42"]]
    assert runtime.query.call_count == 2
    assert len(store._records) == 1
    assert not store._pending and not launcher.active


def test_real_engine_memory_limit_is_422_and_releases_capacity(system):
    client, store, launcher, runtime, _ = system
    runtime.command = [sys.executable, "-c", LOW_MEMORY_WORKER]
    response = client.post(
        "/api/query",
        json={"sql": "SELECT list_sort(range(100000))"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf"},
    )
    assert response.status_code == 422
    assert response.json["error"]["code"] == "query_resource_limit"
    assert "memory" not in response.text.lower()
    assert "query_id" not in response.json
    assert not store._pending and not store._records and not launcher.active
    runtime.terminate_and_reap.assert_called_once_with()
    runtime.command = [
        sys.executable,
        "-m",
        "outage_explorer.entrypoints.query_worker_startup",
    ]
    corrected = client.post(
        "/api/query",
        json={"sql": "SELECT 42"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": "csrf"},
    )
    assert corrected.status_code == 200
    assert corrected.json["rows"] == [["42"]]
    assert not store._pending and not launcher.active
