"""Adversarial transport boundaries; no database or analytical adapters."""

from unittest.mock import Mock

import pytest

from outage_explorer.application import errors
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_services import DataServices
from tests.integration.test_data_api_http import ORIGIN


@pytest.fixture
def transport():
    access = Mock()
    services = DataServices(Mock(), Mock(), Mock(), Mock(), Mock())
    app = create_app(
        Mock(),
        login_service=Mock(),
        access_service=access,
        auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
        data_services=services,
    )
    client = app.test_client()
    return client, access, services


@pytest.mark.parametrize(
    "path",
    [
        "/api/datasets?unexpected=1",
        "/api/datasets?x=1&x=2",
        "/api/refresh/latest?unknown=1",
        "/api/datasets/national/preview?page_size=0",
        "/api/datasets/national/preview?page_size=501",
        "/api/datasets/national/preview?page_size=1&page_size=2",
        "/api/datasets/national/preview?facility=1",
        "/api/datasets/national/preview?start_date=20260901",
        "/api/datasets/national/preview?start_date=2026-02-30",
        "/api/datasets/national/preview?start_date=2026-09-02&end_date=2026-09-01",
        "/api/datasets/national/preview?cursor=x&page_size=1",
        "/api/query?query_id=x",
        "/api/query?page=1",
        "/api/query?query_id=x&page=01",
        "/api/query?query_id=x&page=-1",
        "/api/query?query_id=x&page=1&sql=SELECT",
    ],
)
def test_strict_get_rejects_before_services(transport, path):
    client, _, services = transport
    result = client.get(path)
    assert (
        result.status_code == 400 and result.json["error"]["code"] == "invalid_request"
    )
    assert (
        not services.catalog.mock_calls
        and not services.preview.mock_calls
        and not services.queries.mock_calls
        and not services.refresh.mock_calls
    )


@pytest.mark.parametrize(
    "body",
    [
        '{"sql":"SELECT 1","sql":"SELECT 2"}',
        '{"sql":1}',
        '{"sql":""}',
        '{"sql":"SELECT 1","page":1}',
        "[]",
        "{}",
        "{bad",
        '{"sql":"' + "x" * 65537 + '"}',
        '{"sql":"' + "x" * 140000 + '"}',
    ],
    ids=[
        "duplicate",
        "nonstring",
        "empty",
        "unknown",
        "array",
        "missing",
        "malformed",
        "sql-size",
        "body-size",
    ],
)
def test_strict_query_body(transport, body):
    client, _, services = transport
    response = client.post(
        "/api/query",
        data=body,
        content_type="application/json",
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 400
    assert not services.queries.mock_calls


@pytest.mark.parametrize(
    "path", ["/api/datasets", "/api/query?query_id=x&page=1", "/api/refresh/latest"]
)
def test_get_body_rejected(transport, path):
    assert transport[0].get(path, json={}).status_code == 400


@pytest.mark.parametrize(
    "failure,status,code",
    [
        (errors.UnauthenticatedError("private"), 401, "unauthenticated"),
        (errors.ForbiddenError("private"), 403, "forbidden"),
        (errors.DataUnavailableError("private"), 503, "data_unavailable"),
        (errors.RuntimeUnavailableError("private"), 503, "service_unavailable"),
        (errors.AnalyticalBusyError("private"), 503, "query_busy"),
        (errors.AnalyticalResourceError("private"), 422, "query_resource_limit"),
        (errors.AnalyticalTimeoutError("private"), 504, "query_timeout"),
        (errors.ResultCapacityError(per_user=True), 429, "result_capacity_exhausted"),
        (errors.ResultCapacityError(per_user=False), 503, "result_capacity_exhausted"),
        (SqlRejected("invalid_sql"), 400, "invalid_sql"),
        (SqlRejected(), 400, "unsupported_sql"),
        (errors.QueryUnavailableError("private"), 404, "query_unavailable"),
        (errors.QueryExpiredError("private"), 410, "query_unavailable"),
        (errors.QueryPageError("page_size_mismatch"), 400, "page_size_mismatch"),
        (errors.AccessStoreError("private"), 503, "service_unavailable"),
        (RuntimeError("private"), 503, "service_unavailable"),
    ],
)
def test_safe_errors_and_retry(transport, failure, status, code):
    client, _, services = transport
    services.queries.page.side_effect = failure
    response = client.get("/api/query?query_id=x&page=1", headers={"Origin": ORIGIN})
    assert response.status_code == status and response.json["error"]["code"] == code
    assert "private" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    retry = response.json["error"].get("retry_after_seconds")
    if retry is not None:
        assert str(retry) == response.headers["Retry-After"]


def test_preflight_exact_origins_methods_and_headers(transport):
    client = transport[0]
    headers = {
        "Origin": ORIGIN,
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Content-Type, X-CSRF-Token, Idempotency-Key",
    }
    result = client.options("/api/refresh", headers=headers)
    assert (
        result.status_code == 204
        and "Idempotency-Key" in result.headers["Access-Control-Allow-Headers"]
    )
    assert client.options("/api/query", headers=headers).status_code == 403
    assert client.options("/api/refresh/latest", headers=headers).status_code == 403
    assert (
        client.options(
            "/api/refresh", headers=headers | {"Origin": "http://evil.test"}
        ).status_code
        == 403
    )
    assert (
        client.options(
            "/api/refresh",
            headers=headers | {"Access-Control-Request-Headers": "Authorization"},
        ).status_code
        == 403
    )
    assert (
        client.get(
            "/api/datasets?invalid=1", headers={"Origin": "http://evil.test"}
        ).headers.get("Access-Control-Allow-Origin")
        is None
    )


def test_app_requires_auth_and_construction_is_inert():
    services = DataServices(Mock(), Mock(), Mock(), Mock(), Mock())
    with pytest.raises(ValueError):
        create_app(Mock(), data_services=services)
    app = create_app(
        Mock(),
        login_service=Mock(),
        access_service=Mock(),
        auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
        data_services=services,
    )
    assert (
        len(
            [
                rule
                for rule in app.url_map.iter_rules()
                if rule.rule
                in {
                    "/api/query",
                    "/api/datasets",
                    "/api/datasets/<dataset>/preview",
                    "/api/refresh",
                    "/api/refresh/latest",
                    "/api/refresh/<run_id>",
                }
            ]
        )
        == 7
    )
    assert not any(
        service.mock_calls
        for service in (
            services.catalog,
            services.preview,
            services.queries,
            services.refresh,
        )
    )


def test_latest_no_runs_and_lookup_outage_are_distinct(transport):
    client, _, services = transport
    services.refresh.latest.return_value = None
    response = client.get("/api/refresh/latest")
    assert response.status_code == 200 and response.json == {"run": None}
    services.refresh.latest.side_effect = errors.AccessStoreError("private")
    response = client.get("/api/refresh/latest")
    assert (
        response.status_code == 503
        and response.json["error"]["code"] == "service_unavailable"
    )


def test_refresh_busy_conflict_and_unsupported_bodies(transport):
    client, _, services = transport
    headers = {"Origin": ORIGIN, "Idempotency-Key": "a" * 16}
    for body in ({"start_date": "2026-04-02"}, {"datasets": ["national"]}):
        assert (
            client.post("/api/refresh", json=body, headers=headers).status_code == 400
        )
    assert not services.refresh.mock_calls
    for failure, code in (
        (errors.RefreshBusyError(), "refresh_busy"),
        (errors.IdempotencyConflictError(), "idempotency_conflict"),
    ):
        services.refresh.admit.side_effect = failure
        response = client.post("/api/refresh", json={}, headers=headers)
        assert response.status_code == 409 and response.json["error"]["code"] == code


def test_inert_enabled_bootstrap_and_runtime_gate(monkeypatch):
    from unittest.mock import patch

    from outage_explorer.bootstrap import build_http_app
    from tests.integration.test_user_access_http import CONFIG

    environment = CONFIG | {
        "OUTAGE_DATA_HTTP_ENABLED": "true",
        "OUTAGE_REFRESH_START_DATE": "2026-04-02",
        "OUTAGE_REFRESH_END_DATE": "2026-10-01",
    }
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    with (
        patch("psycopg.connect", side_effect=AssertionError("Database connected")),
        patch("threading.Thread.start", side_effect=AssertionError("Thread started")),
        patch("boto3.Session", side_effect=AssertionError("SDK constructed")),
    ):
        app = build_http_app()
        assert app.test_client().get("/health").status_code == 200
    try:
        assert (
            len(
                [rule for rule in app.url_map.iter_rules() if rule.rule == "/api/query"]
            )
            == 2
        )
        assert "outage_data_start" not in app.extensions
    finally:
        app.extensions["outage_data_close"]()
        app.extensions["outage_data_close"]()


@pytest.mark.parametrize("value", ["yes", "1", "True", "", " false"])
def test_invalid_data_enablement(value):
    from outage_explorer.settings import data_http_settings

    with pytest.raises(ValueError):
        data_http_settings({"OUTAGE_DATA_HTTP_ENABLED": value})
