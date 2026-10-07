"""Seven HTTP contracts with real PostgreSQL, Parquet and controlled workers."""

import json
from datetime import timedelta
from decimal import Decimal
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
from tests.integration.test_catalog_preview import (
    portable_parquet_selection as portable_parquet_selection,
)
from tests.integration.test_catalog_preview import (
    portable_selection as portable_selection,
)
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
    from outage_explorer.infrastructure.local_cache.modeled import VerifiedResourceCache
    from outage_explorer.infrastructure.query_results.previews import (
        BoundedPreviewSequences,
    )
    from outage_explorer.infrastructure.query_results.store import BoundedQueryResults
    from outage_explorer.infrastructure.s3.resources import S3ResourceStore
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
        objects = S3ResourceStore(browsing[5], "test-bucket", "connector/", ARTIFACT)
        # Fresh private cache/output/key on each explicit start.
        cache = VerifiedResourceCache(
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


def preview_http_client(state):
    """Actual HTTP/application authorization and lifecycle with injected ports."""
    access = state.service._access
    app = create_app(
        HealthService(state.clock),
        login_service=Mock(),
        access_service=access,
        auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
        data_services=DataServices(
            CatalogService(access, state.publications),
            state.service,
            Mock(),
            Mock(),
            PreviewEncoding(ENCODING),
        ),
    )
    client = app.test_client()
    client.set_cookie("outage_session", state.token)
    return client, state


@pytest.fixture
def portable_preview_http(portable_selection):
    return preview_http_client(portable_selection)


@pytest.mark.parametrize("dataset", ["facilities", "generators"])
@pytest.mark.parametrize("facility", ["001", "A' OR 1=1 --", "é", "%FF"])
def test_portable_http_facility_filter_and_cursor_forwarding(
    portable_preview_http, dataset, facility
):
    client, state = portable_preview_http
    first = client.get(
        f"/api/datasets/{dataset}/preview",
        query_string={
            "facility": facility,
            "start_date": "2026-09-01",
            "end_date": "2026-09-02",
            "page_size": "1",
        },
    )
    assert first.status_code == 200
    validator("Preview").validate(first.json)
    assert state.requests[-1].facility == facility
    assert state.requests[-1].start.isoformat() == "2026-09-01"
    assert state.requests[-1].end.isoformat() == "2026-09-02"
    assert state.requests[-1].size == 1
    second = client.get(
        f"/api/datasets/{dataset}/preview",
        query_string={"cursor": first.json["next_cursor"]},
    )
    assert second.status_code == 200
    assert state.requests[-1].facility == facility
    revisit = client.get(
        f"/api/datasets/{dataset}/preview",
        query_string={"cursor": first.json["page_cursor"]},
    )
    assert revisit.json == first.json


@pytest.mark.parametrize(
    "query",
    [
        "facility=",
        "facility=%20001",
        "facility=001%20",
        "facility=%00",
        "facility=%C2%85",
        "facility=%FF",
        "facility=%ED%A0%80",
        "facility=001&facility=001",
        "facility=001&cursor=anything",
        "facility=" + "x" * 257,
    ],
)
def test_portable_http_rejects_invalid_facility_before_resources(
    portable_preview_http, query
):
    client, state = portable_preview_http
    response = client.get("/api/datasets/facilities/preview?" + query)
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"
    assert state.requests == []
    state.inputs.prepare.assert_not_called()


@pytest.mark.parametrize("facility", ["", "001"])
def test_portable_http_national_rejects_facility(portable_preview_http, facility):
    client, state = portable_preview_http
    response = client.get(
        "/api/datasets/national/preview", query_string={"facility": facility}
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"
    assert state.requests == []
    state.inputs.prepare.assert_not_called()


@pytest.mark.parametrize(
    "denial",
    ["viewer", "missing", "revoked", "expired", "changed_role", "foreign_cursor"],
)
@pytest.mark.parametrize("dataset", ["facilities", "generators"])
def test_portable_http_facility_authorization_precedes_resources(
    portable_preview_http, denial, dataset
):
    from dataclasses import replace

    client, state = portable_preview_http
    cursor = None
    if denial in {"changed_role", "foreign_cursor"}:
        first = client.get(f"/api/datasets/{dataset}/preview?facility=001&page_size=1")
        assert first.status_code == 200
        cursor = first.json["next_cursor"]
    current = state.sessions.resolve_session.return_value
    if denial in {"viewer", "changed_role"}:
        state.sessions.resolve_session.return_value = replace(
            current, user=replace(current.user, role=Role.VIEWER)
        )
    elif denial == "missing":
        client.delete_cookie("outage_session")
    elif denial == "revoked":
        state.sessions.resolve_session.return_value = None
    elif denial == "expired":
        state.clock.value = current.expires_at
    else:
        state.sessions.resolve_session.return_value = replace(
            current, user=replace(current.user, id="another-analyst")
        )
    state.requests.clear()
    state.inputs.prepare.reset_mock()
    response = client.get(
        f"/api/datasets/{dataset}/preview",
        query_string={"cursor": cursor} if cursor else {"facility": "001"},
    )
    assert response.status_code == (
        401
        if denial in {"missing", "revoked", "expired"}
        else 404
        if denial in {"viewer", "changed_role"}
        else 410
    )
    assert state.requests == []
    state.inputs.prepare.assert_not_called()


def test_portable_http_catalog_filters_match_grains(portable_preview_http):
    from dataclasses import replace
    from datetime import date

    from outage_explorer.domain.access import AnalyticalGrain
    from outage_explorer.domain.publication import DatasetSummary

    client, state = portable_preview_http
    current = state.publications.active_generation.return_value
    state.publications.active_generation.return_value = replace(
        current,
        datasets=tuple(
            DatasetSummary(
                grain,
                "v1",
                1,
                date(2026, 9, 1),
                date(2026, 9, 2),
                f"prefix/generations/old/{dataset}.parquet",
                "a" * 64,
                100,
            )
            for grain, dataset in zip(
                AnalyticalGrain, ["national", "facilities", "generators"], strict=True
            )
        ),
    )
    response = client.get("/api/datasets")
    assert response.status_code == 200
    validator("Catalog").validate(response.json)
    assert {d["id"]: d["supported_filters"] for d in response.json["datasets"]} == {
        "national": ["start_date", "end_date"],
        "facilities": ["start_date", "end_date", "facility"],
        "generators": ["start_date", "end_date", "facility"],
    }
    assert state.requests == []
    state.inputs.prepare.assert_not_called()


@pytest.mark.parametrize("dataset", ["facilities", "generators"])
@pytest.mark.parametrize("role", [Role.ANALYST, Role.ADMIN])
def test_filtered_http_real_worker_snapshot_pages(
    portable_parquet_selection, dataset, role
):
    """HTTP to real Parquet/JSON worker, including frozen publication and revisits."""
    from dataclasses import replace

    state = portable_parquet_selection
    current = state.sessions.resolve_session.return_value
    state.sessions.resolve_session.return_value = replace(
        current, user=replace(current.user, role=role)
    )
    client, _ = preview_http_client(state)
    path = f"/api/datasets/{dataset}/preview"
    first = client.get(
        path,
        query_string={
            "facility": "001",
            "start_date": "2026-09-02",
            "end_date": "2026-09-03",
            "page_size": 1,
        },
    )
    assert first.status_code == 200
    original = first.json
    state.publications.active_generation.return_value = state.next_generation
    pages = [original]
    while pages[-1]["has_more"]:
        response = client.get(path, query_string={"cursor": pages[-1]["next_cursor"]})
        assert response.status_code == 200
        pages.append(response.json)
    columns = [column["name"] for column in original["columns"]]
    identity = [
        columns.index(name)
        for name in ("period", "facility", "generator")
        if name in columns
    ]
    keys = [
        tuple(row[index] for index in identity)
        for page in pages
        for row in page["rows"]
    ]
    expected = [
        (day, "001", *([generator] if dataset == "generators" else []))
        for day in ("2026-09-03", "2026-09-02")
        for generator in (("01", "A", "é") if dataset == "generators" else (None,))
    ]
    assert keys == expected
    assert len(keys) == len(set(keys))
    assert all(page["generation_id"] == original["generation_id"] for page in pages)
    assert state.inputs.prepare.call_count == 1
    for page in pages:
        assert (
            client.get(path, query_string={"cursor": page["page_cursor"]}).json == page
        )
    calls = len(state.requests)
    assert (
        client.get(
            path, query_string={"cursor": original["page_cursor"], "facility": "001"}
        ).status_code
        == 400
    )
    assert len(state.requests) == calls
    fresh = client.get(path, query_string={"facility": "001"})
    assert fresh.status_code == 200 and fresh.json["generation_id"] == "new-publication"
    assert fresh.json["rows"][0] != original["rows"][0]
    assert Decimal(fresh.json["rows"][0][columns.index("capacity_mw")]) == 200
    assert Decimal(original["rows"][0][columns.index("capacity_mw")]) != 200
    # Both omitted-filter and date-only requests use the real worker and all IDs.
    for query, count in (
        ({}, 27 if dataset == "generators" else 9),
        (
            {"start_date": "2026-09-02", "end_date": "2026-09-02"},
            9 if dataset == "generators" else 3,
        ),
    ):
        response = client.get(path, query_string=query)
        assert response.status_code == 200
        assert len(response.json["rows"]) == count
        assert {row[columns.index("period")] for row in response.json["rows"]} == (
            {"2026-09-02"} if query else {"2026-09-01", "2026-09-02", "2026-09-03"}
        )
        assert {row[columns.index("facility")] for row in response.json["rows"]} == {
            "001",
            "1",
            "other",
        }
    state.sequences.close()
    assert all(entry.pins == 0 for entry in state.cache._entries.values())
