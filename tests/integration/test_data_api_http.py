"""Seven HTTP contracts with real PostgreSQL, Parquet and controlled workers."""

import json
from datetime import timedelta
from unittest.mock import Mock

import psycopg
import pytest

from outage_explorer.application.services.catalog import CatalogService
from outage_explorer.application.services.health import HealthService
from outage_explorer.domain.access import Role
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.sql_validation.inspection import DuckdbSqlInspector
from tests.integration import test_query_results as retained
from tests.integration.test_catalog_preview import ENCODING
from tests.unit.test_data_api_contract import validator

# Test injection uses controlled subprocesses; it never establishes OS isolation.
database = retained.database
system = retained.system
browsing = retained.browsing
queries = retained.queries
ORIGIN = "http://localhost:3000"


def app_for(system, browsing, queries):
    access = system[1]._access
    transport = AuthTransport(ORIGIN, frozenset({ORIGIN}), True)
    return create_app(
        HealthService(browsing[3]),
        login_service=Mock(),
        access_service=access,
        auth_transport=transport,
        data_services=DataServices(
            CatalogService(access, system[0]),
            browsing[0],
            queries[0],
            system[1],
            PreviewEncoding(ENCODING),
        ),
    )


@pytest.fixture
def app(system, browsing, queries):
    return app_for(system, browsing, queries)


def client_for(app, system, role=Role.ADMIN):
    client = app.test_client()
    token = system[2][role]
    client.set_cookie("outage_session", token)
    csrf = system[1]._access.current_identity(token).csrf_token
    return client, {
        "Origin": ORIGIN,
        "X-CSRF-Token": csrf,
        "Idempotency-Key": "http-test-key-0001",
    }


@pytest.mark.parametrize("role", list(Role))
def test_http_catalog_preview_query_and_headers(app, system, role):
    client, headers = client_for(app, system, role)
    catalog = client.get("/api/datasets", headers=headers)
    assert catalog.status_code == 200
    validator("Catalog").validate(catalog.json)
    assert [d["id"] for d in catalog.json["datasets"]] == (
        ["national"]
        if role is Role.VIEWER
        else ["national", "facilities", "generators"]
    )
    preview = client.get(
        "/api/datasets/national/preview?start_date=2026-09-01&end_date=2026-09-02&page_size=1",
        headers=headers,
    )
    assert preview.status_code == 200
    validator("Preview").validate(preview.json)
    again = client.get(
        "/api/datasets/national/preview",
        query_string={"cursor": preview.json["page_cursor"]},
        headers=headers,
    )
    assert again.json == preview.json
    sql = client.post(
        "/api/query?page=1&page_size=1",
        json={"sql": "SELECT 1 AS x UNION ALL SELECT 2 AS x"},
        headers=headers,
    )
    assert sql.status_code == 200
    validator("QueryResult").validate(sql.json)
    page = client.get(
        "/api/query",
        query_string={"query_id": sql.json["query_id"], "page": 2},
        headers=headers,
    )
    assert page.json["rows"] == [["2"]]
    for response in (catalog, preview, sql, page):
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert (
            response.headers["Access-Control-Expose-Headers"] == "Location, Retry-After"
        )
        assert "Origin" in response.headers["Vary"]


def test_http_denials_current_role_ownership_and_csrf(app, system, queries, database):
    admin, headers = client_for(app, system)
    viewer, viewer_headers = client_for(app, system, Role.VIEWER)
    assert viewer.get("/api/datasets/facilities/preview").status_code == 404
    assert viewer.get("/api/datasets/secret/preview").status_code == 404
    assert (
        viewer.post(
            "/api/query",
            json={"sql": "SELECT * FROM facilities"},
            headers=viewer_headers,
        ).status_code
        == 403
    )
    assert (
        viewer.post("/api/refresh", json={}, headers=viewer_headers).status_code == 403
    )
    assert admin.post("/api/query", json={"sql": "SELECT 1"}).status_code == 403
    assert (
        admin.post(
            "/api/query",
            json={"sql": "SELECT 1"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": "bad"},
        ).status_code
        == 403
    )
    first = admin.post(
        "/api/query", json={"sql": "SELECT facility FROM facilities"}, headers=headers
    )
    identity = first.json["query_id"]
    assert (
        viewer.get(
            "/api/query", query_string={"query_id": identity, "page": 1}
        ).status_code
        == 404
    )
    with psycopg.connect(database) as conn:
        conn.execute(
            "UPDATE users SET role_code = 'viewer' WHERE id = %s",
            (system[3][Role.ADMIN].id,),
        )
    assert (
        admin.get(
            "/api/query", query_string={"query_id": identity, "page": 1}
        ).status_code
        == 403
    )
    assert len(queries[3].calls) == 1


def test_refresh_durable_receipt_latest_and_timestamp_projection(app, system):
    client, headers = client_for(app, system)
    prior = client.get("/api/refresh/latest")
    assert prior.json["run"] is not None  # browsing fixture published a generation.
    response = client.post("/api/refresh", json={}, headers=headers)
    assert response.status_code == 202
    validator("RefreshReceipt").validate(response.json)
    assert response.headers["Location"] == response.json["status_url"]
    assert response.headers["Retry-After"] == "3"
    run = system[0].get_run(response.json["run_id"])
    assert run.status.value == "accepted" and run.started_at is None
    retry = client.post("/api/refresh", json={}, headers=headers)
    assert retry.json == response.json
    status = client.get(response.json["status_url"])
    validator("RefreshRun").validate(status.json)
    assert status.json["started_at"] is None and status.json["finished_at"] is None
    assert client.get("/api/refresh/latest").json["run"] == status.json
    body = json.dumps(status.json)
    assert not any(
        name in body for name in ("key_digest", "requester_id", "manifest", "epoch")
    )


def test_out_of_range_expiry_loss_and_no_rerun(app, system, browsing, queries):
    client, headers = client_for(app, system)
    first = client.post("/api/query?page=2", json={"sql": "SELECT 42"}, headers=headers)
    assert (
        first.status_code == 400 and first.json["error"]["code"] == "page_out_of_range"
    )
    identity = first.json["error"]["details"]["query_id"]
    assert client.get(
        "/api/query", query_string={"query_id": identity, "page": 1}
    ).json["rows"] == [["42"]]
    preview = client.get("/api/datasets/national/preview")
    browsing[3].value += timedelta(seconds=60)
    assert (
        client.get(
            "/api/datasets/national/preview",
            query_string={"cursor": preview.json["page_cursor"]},
        ).status_code
        == 410
    )
    assert (
        client.get(
            "/api/query", query_string={"query_id": identity, "page": 1}
        ).status_code
        == 410
    )
    assert client.get("/api/query?query_id=unknown&page=1").status_code == 404
    assert len(queries[3].calls) == 1


@pytest.fixture
def supervised_http(system, browsing, tmp_path):
    """Use the delivered forwarding ports with real Parquet/controlled workers."""
    from outage_explorer.bootstrap import DataHttpResources, build_data_services
    from outage_explorer.infrastructure.local_cache.modeled import VerifiedModeledCache
    from outage_explorer.infrastructure.query_results.previews import (
        BoundedPreviewSequences,
    )
    from outage_explorer.infrastructure.query_results.store import BoundedQueryResults
    from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
    from outage_explorer.infrastructure.security import RandomSecurityMaterial
    from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
    from outage_explorer.infrastructure.worker_runtime.ownership import RecoveryOwner
    from outage_explorer.infrastructure.worker_runtime.supervisor import (
        AnalyticalResources,
        AnalyticalSupervisor,
    )
    from tests.integration.test_analytical_supervisor import evidence, profile
    from tests.integration.test_catalog_preview import ARTIFACT, CACHE, METADATA

    candidate = profile(tmp_path / "supervisor")
    clock = browsing[3]
    states = []

    def construct(ledger, key):
        objects = S3ArtifactStore(browsing[5], "test-bucket", "connector/", ARTIFACT)
        # Fresh private cache/output/key on each explicit start.
        cache = VerifiedModeledCache(
            tmp_path / f"supervised-cache-{len(states)}", objects, ARTIFACT, CACHE
        )
        runtime = retained.QueryRuntime()
        recovery = RecoveryOwner()
        launcher = VerifiedLauncher(
            candidate.execution_bounds,
            runtime,
            evidence="controlled supervisor fixture",
            recovery=recovery,
        )
        results = BoundedQueryResults(
            tmp_path / "supervised-results", clock, retained.BOUNDS
        )
        sequences = BoundedPreviewSequences(clock, METADATA, key)
        state = AnalyticalResources(
            cache,
            launcher,
            results,
            sequences,
            recovery,
            runtime.terminate_and_reap,
            lambda: None,
            cache.close,
        )
        states.append((state, runtime, cache))
        return state

    def build():
        supervisor = AnalyticalSupervisor(
            candidate, evidence(candidate), construct, lambda ledger: None
        )
        resources = DataHttpResources(
            supervisor.inputs,
            supervisor.execution,
            supervisor.results,
            supervisor.sequences,
            PreviewEncoding(ENCODING),
            1024**2,
            supervisor.start,
            supervisor.close,
            candidate.identity,
            inspector=DuckdbSqlInspector(
                max_sql_bytes=65536, max_nodes=10000, max_depth=64
            ),
        )
        services = build_data_services(
            system[1]._access,
            system[0],
            RandomSecurityMaterial(),
            {
                "OUTAGE_REFRESH_START_DATE": "2026-04-02",
                "OUTAGE_REFRESH_END_DATE": "2026-10-01",
            },
            resources,
        )
        app = create_app(
            HealthService(clock),
            login_service=Mock(),
            access_service=system[1]._access,
            auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
            data_services=services,
        )
        app.extensions["controlled_data_services"] = services
        return supervisor, app

    supervisor, app = build()
    try:
        yield supervisor, app, states, build
    finally:
        supervisor.close()


def test_supervised_http_start_paging_restart_and_current_role(
    supervised_http, system, database
):
    supervisor, app, states, rebuild = supervised_http
    client, headers = client_for(app, system, Role.ANALYST)
    assert client.get("/health").status_code == 200
    assert client.get("/api/datasets").status_code == 200
    assert (
        client.post("/api/query", json={"sql": "SELECT 1"}, headers=headers).status_code
        == 503
    )
    assert states == []
    supervisor.start()
    preview = client.get("/api/datasets/national/preview?page_size=1")
    assert preview.status_code == 200
    first = client.post(
        "/api/query?page_size=1",
        json={"sql": "SELECT period FROM facilities ORDER BY period, facility"},
        headers=headers,
    )
    assert first.status_code == 200
    calls = len(states[0][1].calls)
    revisit = client.get(
        "/api/query", query_string={"query_id": first.json["query_id"], "page": 1}
    )
    second = client.get(
        "/api/query", query_string={"query_id": first.json["query_id"], "page": 2}
    )
    assert revisit.json == first.json
    assert second.status_code == 200
    assert len(states[0][1].calls) == calls
    token = system[2][Role.ANALYST]
    user_id = system[1]._access.current_identity(token).user.id
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE users SET role_code = 'viewer' WHERE id = %s", (user_id,)
        )
    # Viewer cannot execute facilities SQL; denial precedes input/launcher.
    assert (
        client.post(
            "/api/query", json={"sql": "SELECT period FROM facilities"}, headers=headers
        ).status_code
        == 403
    )
    assert len(states[0][1].calls) == calls
    assert (
        client.get(
            "/api/query", query_string={"query_id": first.json["query_id"], "page": 2}
        ).status_code
        == 403
    )
    assert len(states[0][1].calls) == calls
    supervisor.close()
    restarted, fresh_app = rebuild()
    try:
        restarted.start()
        fresh, _ = client_for(fresh_app, system, Role.ANALYST)
        lost = fresh.get(
            "/api/query", query_string={"query_id": first.json["query_id"], "page": 2}
        )
        assert lost.status_code == 404
        cursor = fresh.get(
            "/api/datasets/national/preview",
            query_string={"cursor": preview.json["page_cursor"]},
        )
        assert cursor.status_code == 410
        assert not states[1][1].calls
        fresh_admin, _ = client_for(fresh_app, system, Role.ADMIN)
        assert fresh_admin.get("/api/refresh/latest").status_code == 200
        assert (
            fresh.get("/api/datasets/national/preview?page_size=1").status_code == 200
        )
    finally:
        restarted.close()
