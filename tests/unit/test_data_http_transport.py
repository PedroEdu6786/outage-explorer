"""Adversarial transport boundaries; no database or analytical adapters."""

import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from outage_explorer.application import errors
from outage_explorer.application.catalog_responses import (
    CatalogDatasetResult,
    CatalogResult,
)
from outage_explorer.application.dto import CatalogAccess, RequestAccess
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.application.refresh_request import RefreshAdmissionRequest
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.refresh import RefreshService
from outage_explorer.domain.access import Role, SeededUser, Session
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import (
    PublicationState,
    RefreshConfiguration,
    RefreshRun,
    RefreshStage,
    RunStatus,
)
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.transport.auth import AuthTransport
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from tests.integration.test_data_api_http import ORIGIN


@pytest.fixture
def transport():
    access = Mock()
    access.resolve.return_value = SimpleNamespace(user=SimpleNamespace(role=Role.ADMIN))
    context = RequestAccess(SimpleNamespace(id="admin", role=Role.ADMIN))
    access.authenticate.return_value = context
    access.validate_csrf.return_value = context
    access.require_roles.side_effect = lambda context, roles: context
    access.require_catalog.return_value = CatalogAccess(
        context.principal, PUBLIC_DATASETS
    )
    services = DataServices(Mock(), Mock(), Mock(), Mock(), Mock(), Mock())
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
        "/api/refresh/run-123?unknown=1",
        "/api/refresh/" + "a" * 4097,
        "/api/datasets/national/preview?page_size=0",
        "/api/datasets/national/preview?page_size=501",
        "/api/datasets/national/preview?page_size=1&page_size=2",
        "/api/datasets/facilities/preview?facility=1&facility=1",
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
        and not services.query_pages.mock_calls
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
    "query",
    [
        "page=0",
        "page=-1",
        "page=2147483648",
        "page=1&page=2",
        "page_size=0",
        "page_size=501",
        "page_size=1&page_size=2",
    ],
)
def test_invalid_submission_pagination_is_rejected_before_execution(transport, query):
    client, _, services = transport
    response = client.post(
        f"/api/query?{query}", json={"sql": "SELECT 1"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 400
    services.queries.execute.assert_not_called()


@pytest.mark.parametrize(
    "sql",
    ["SELECT '\ud800'", "SELECT '\udfff'", "SELECT '\ud800x'", "SELECT '\udc00\ud800'"],
)
def test_query_rejects_unpaired_surrogates_before_services(transport, sql):
    client, _, services = transport
    response = client.post("/api/query", json={"sql": sql}, headers={"Origin": ORIGIN})
    assert response.status_code == 400
    assert response.json == {
        "error": {"code": "invalid_request", "message": "Invalid request"}
    }
    assert not services.queries.mock_calls


@pytest.mark.parametrize(
    "sql,status",
    [
        ("SELECT 'español'", 200),
        ("SELECT '😀'", 200),
        ("é" * 32768, 200),
        ("é" * 32769, 400),
    ],
    ids=["unicode", "supplementary-character", "byte-limit", "over-byte-limit"],
)
def test_query_preserves_valid_unicode_and_enforces_utf8_byte_limit(
    transport, sql, status
):
    client, _, services = transport
    services.queries.execute.return_value = {"accepted": True}
    body = json.dumps({"sql": sql}, ensure_ascii=False).encode("utf-8")
    response = client.post(
        "/api/query",
        data=body,
        content_type="application/json",
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == status
    if status == 200:
        assert services.queries.execute.call_args.args[1] == sql
        assert services.queries.execute.call_count == 1
    else:
        assert response.json["error"]["code"] == "invalid_request"
        assert not services.queries.mock_calls


@pytest.mark.parametrize(
    "path",
    [
        "/api/datasets",
        "/api/query?query_id=x&page=1",
        "/api/refresh/latest",
        "/api/refresh/run-123",
    ],
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
    services.query_pages.read.side_effect = failure
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
    services = DataServices(Mock(), Mock(), Mock(), Mock(), Mock(), Mock())
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
            services.query_pages,
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


@pytest.mark.parametrize(
    "key", [None, "", "a" * 15, "a" * 129, "a" * 15 + " ", "a" * 15 + "é"]
)
def test_refresh_rejects_invalid_keys_before_service(transport, key):
    client, _, services = transport
    headers = {"Origin": ORIGIN}
    if key is not None:
        headers["Idempotency-Key"] = key
    response = client.post("/api/refresh", json={}, headers=headers)
    assert response.status_code == 400
    services.refresh.admit.assert_not_called()


def test_refresh_passes_validated_dto_and_verified_access(transport):
    client, access, services = transport
    client.set_cookie("outage_session", "session-token")
    services.refresh.admit.side_effect = errors.RefreshBusyError()
    key = "request-key-00001"
    response = client.post(
        "/api/refresh", json={}, headers={"Origin": ORIGIN, "Idempotency-Key": key}
    )
    assert response.status_code == 409
    services.refresh.admit.assert_called_once_with(
        access.validate_csrf.return_value, RefreshAdmissionRequest(idempotency_key=key)
    )
    access.authenticate.assert_not_called()
    access.require_roles.assert_called_once_with(
        access.validate_csrf.return_value, ("admin",)
    )


@pytest.mark.parametrize("role", [Role.VIEWER, Role.ANALYST])
@pytest.mark.parametrize(
    "path", ["/api/refresh", "/api/refresh/latest", "/api/refresh/unknown"]
)
def test_refresh_role_guard_rejects_before_parsing_and_service(transport, role, path):
    client, access, services = transport
    access.require_roles.side_effect = errors.ForbiddenError()
    if path == "/api/refresh":
        response = client.post(path, data="invalid json", headers={"Origin": ORIGIN})
    else:
        response = client.get(path + "?unexpected=1")
    assert response.status_code == 403
    assert not services.refresh.mock_calls


@pytest.mark.parametrize(
    "path", ["/api/refresh", "/api/refresh/latest", "/api/refresh/unknown"]
)
def test_refresh_requires_authentication_before_parsing(transport, path):
    client, access, services = transport
    access.authenticate.side_effect = errors.UnauthenticatedError()
    access.validate_csrf.side_effect = errors.UnauthenticatedError()
    if path == "/api/refresh":
        response = client.post(path, data="invalid json", headers={"Origin": ORIGIN})
    else:
        response = client.get(path + "?unexpected=1")
    assert response.status_code == 401
    assert not services.refresh.mock_calls


def test_refresh_csrf_guard_rejects_before_role_guard_and_service(transport):
    client, access, services = transport
    access.validate_csrf.side_effect = errors.ForbiddenError()
    response = client.post("/api/refresh", json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403
    access.require_roles.assert_not_called()
    assert not services.refresh.mock_calls


def test_refresh_resolves_session_once_and_does_not_reuse_access_on_later_requests():
    now = datetime(2026, 10, 10, tzinfo=UTC)
    token = "a" * 43
    security = RandomSecurityMaterial()
    user = SeededUser("admin-id", "issuer", "subject", "admin@test", Role.ADMIN)
    session = Session(security.digest(token), user, now, now + timedelta(hours=1))
    sessions = Mock()
    sessions.resolve_session.return_value = session
    clock = Mock()
    clock.now.return_value = now
    access = AccessService(sessions, security, clock)
    store = Mock()
    store.replay.return_value = None

    @contextmanager
    def busy_admission():
        yield SimpleNamespace(replay=lambda user, digest: None, active_run_id="busy")

    store.admission_transaction.side_effect = busy_admission
    store.latest.return_value = None
    configuration = RefreshConfiguration(
        start=date(2026, 4, 2),
        end=date(2026, 10, 10),
        max_interval_days=192,
        source_interval_days=192,
        model_interval_days=192,
        candidate_seconds=1800,
        persistence_seconds=1800,
    )
    refresh = RefreshService(access, store, lambda: configuration, security)
    app = create_app(
        Mock(),
        login_service=Mock(),
        access_service=access,
        auth_transport=AuthTransport(ORIGIN, frozenset({ORIGIN}), True),
        data_services=DataServices(Mock(), Mock(), Mock(), Mock(), refresh, Mock()),
    )
    client = app.test_client()
    client.set_cookie("outage_session", token)
    key = "single-resolution-key"
    headers = {
        "Origin": ORIGIN,
        "X-CSRF-Token": security.csrf_token(token),
        "Idempotency-Key": key,
    }

    assert client.post("/api/refresh", json={}, headers=headers).status_code == 409
    assert sessions.resolve_session.call_count == 1
    store.replay.assert_called_once_with(user.id, security.digest(key))
    store.admission_transaction.assert_called_once_with()

    assert client.get("/api/refresh/latest").status_code == 200
    assert sessions.resolve_session.call_count == 2
    store.get_run.return_value = None
    assert (
        client.get("/api/refresh/00000000-0000-0000-0000-000000000001").status_code
        == 404
    )
    assert sessions.resolve_session.call_count == 3
    sessions.resolve_session.return_value = replace(
        session, user=replace(user, role=Role.VIEWER)
    )
    assert client.post("/api/refresh", json={}, headers=headers).status_code == 403
    assert sessions.resolve_session.call_count == 4
    assert store.admission_transaction.call_count == 1
    sessions.resolve_session.return_value = None
    assert client.get("/api/refresh/latest").status_code == 401
    assert sessions.resolve_session.call_count == 5
    store.latest.assert_called_once()


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


@pytest.fixture
def refresh_run():
    return RefreshRun(
        id="run-123",
        requester_id="private-user",
        key_digest="private-key",
        configuration=RefreshConfiguration(
            start=date(2026, 4, 2),
            end=date(2026, 10, 1),
            max_interval_days=183,
            source_interval_days=183,
            model_interval_days=183,
            candidate_seconds=1800,
            persistence_seconds=1800,
        ),
        base_generation_id=None,
        status=RunStatus.ACCEPTED,
        stage=RefreshStage.QUEUED,
        admitted_at=datetime(2026, 10, 1, tzinfo=UTC),
        epoch=None,
        generation_id=None,
        publication=PublicationState.PENDING,
        quality_json=None,
        failure=None,
        no_publication_reason=None,
    )


@pytest.mark.parametrize(
    "status,code",
    [
        (RunStatus.ACCEPTED, 202),
        (RunStatus.RUNNING, 202),
        (RunStatus.PUBLICATION_UNKNOWN, 202),
        (RunStatus.SUCCEEDED, 200),
        (RunStatus.RETAINED, 200),
        (RunStatus.FAILED, 200),
        (RunStatus.INTERRUPTED, 200),
    ],
)
def test_refresh_admission_response_contract(transport, refresh_run, status, code):
    client, _, services = transport
    services.refresh.admit.return_value = replace(refresh_run, status=status)
    response = client.post(
        "/api/refresh",
        json={},
        headers={
            "Origin": ORIGIN,
            "Idempotency-Key": "a" * 16,
        },
    )
    assert response.status_code == code
    assert response.json == {
        "run_id": "run-123",
        "status": status.value,
        "effective_interval": {"start_date": "2026-04-02", "end_date": "2026-10-01"},
        "status_url": "/api/refresh/run-123",
    }
    assert response.headers["Location"] == "/api/refresh/run-123"
    assert response.headers["Retry-After"] == "3"
    assert response.headers["Cache-Control"] == "no-store"


def test_refresh_read_response_envelopes_and_private_fields(transport, refresh_run):
    client, _, services = transport
    services.refresh.status.return_value = refresh_run
    services.refresh.latest.return_value = refresh_run
    status = client.get("/api/refresh/run-123")
    latest = client.get("/api/refresh/latest")
    assert status.status_code == latest.status_code == 200
    assert latest.json == {"run": status.json}
    assert set(status.json) == {
        "run_id",
        "status",
        "stage",
        "effective_interval",
        "accepted_at",
        "started_at",
        "finished_at",
        "datasets",
        "publication",
        "failure",
    }
    assert status.json["run_id"] == "run-123"
    assert status.json["accepted_at"] == "2026-10-01T00:00:00Z"
    assert "private-user" not in status.text and "private-key" not in status.text
    services.refresh.status.return_value = None
    missing = client.get("/api/refresh/missing")
    assert missing.status_code == 404
    assert missing.json == {
        "error": {
            "code": "refresh_unavailable",
            "message": "Refresh unavailable",
        }
    }
    assert missing.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize(
    "path,method,idempotency",
    [
        ("/api/auth/login", "GET", False),
        ("/api/auth/callback", "POST", False),
        ("/api/auth/session", "GET", False),
        ("/api/auth/logout", "POST", False),
        ("/api/datasets", "GET", False),
        ("/api/datasets/national/preview", "GET", False),
        ("/api/query", "GET", False),
        ("/api/query", "POST", False),
        ("/api/refresh", "POST", True),
        ("/api/refresh/latest", "GET", True),
        ("/api/refresh/run-123", "GET", True),
    ],
)
def test_central_preflight_policies_do_not_invoke_services(
    transport, path, method, idempotency
):
    client, access, services = transport
    requested_headers = "Content-Type, X-CSRF-Token"
    if idempotency:
        requested_headers += ", Idempotency-Key"
    response = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": requested_headers,
        },
    )
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == ORIGIN
    assert response.headers["Access-Control-Allow-Credentials"] == "true"
    assert method in response.headers["Access-Control-Allow-Methods"]
    assert (
        "Idempotency-Key" in response.headers["Access-Control-Allow-Headers"]
    ) == idempotency
    assert not access.mock_calls
    for service in (
        services.catalog,
        services.preview,
        services.queries,
        services.query_pages,
        services.refresh,
    ):
        assert not service.mock_calls


@pytest.mark.parametrize("path", ["/api/auth/missing", "/api/refresh/missing/path"])
def test_unmatched_preflight_remains_a_sanitized_routing_error(transport, path):
    client, _, _ = transport
    response = client.options(
        path,
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_request"
    assert "Access-Control-Allow-Methods" not in response.headers


def test_unrelated_routing_errors_keep_their_http_status(transport):
    client, _, _ = transport
    assert client.get("/unregistered").status_code == 404
    assert client.post("/health").status_code == 405


@pytest.mark.parametrize(
    ("path", "auth_method"),
    [
        ("/api/datasets?unknown=1", "authenticate"),
        ("/api/query?page=bad", "current_identity"),
    ],
)
def test_catalog_and_query_authenticate_before_validation(transport, path, auth_method):
    client, access, services = transport
    getattr(access, auth_method).side_effect = errors.UnauthenticatedError()
    response = client.get(path)
    assert response.status_code == 401
    assert not services.catalog.mock_calls
    assert not services.queries.mock_calls
    assert not services.query_pages.mock_calls


def test_query_csrf_denies_before_parsing_or_execution(transport):
    client, access, services = transport
    access.validate_csrf.side_effect = errors.ForbiddenError()
    response = client.post(
        "/api/query?page=bad", data="invalid", headers={"Origin": ORIGIN}
    )
    assert response.status_code == 403
    services.queries.execute.assert_not_called()


def test_query_dtos_forward_unchanged_sql_and_pagination(transport):
    client, _, services = transport
    client.set_cookie("outage_session", "session-token")
    payload = {"rows": [[1]], "page": 2, "query_id": "retained-id"}
    services.queries.execute.return_value = payload
    services.query_pages.read.return_value = payload
    sql = "  SELECT 1;\n"
    response = client.post(
        "/api/query?page=2&page_size=25", json={"sql": sql}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200 and response.json == payload
    services.queries.execute.assert_called_once_with(
        "session-token", sql, page=2, page_size=25
    )
    response = client.get("/api/query?query_id=retained-id&page=2")
    assert response.status_code == 200 and response.json == payload
    services.query_pages.read.assert_called_once_with(
        "session-token", "retained-id", page=2, page_size=None
    )
    assert services.queries.execute.call_count == 1


def test_catalog_payload_is_not_reenveloped(transport):
    client, access, services = transport
    client.set_cookie("outage_session", "session-token")
    services.catalog.describe.return_value = CatalogResult(
        generation_id="generation",
        datasets=(
            CatalogDatasetResult(
                dataset=PUBLIC_DATASETS[0], columns=[{"name": "period"}], coverage=None
            ),
        ),
    )
    response = client.get("/api/datasets")
    assert response.status_code == 200
    assert response.json == {
        "generation_id": "generation",
        "datasets": [
            {
                "id": "national",
                "sql_name": "national",
                "label": "National",
                "schema_version": "1",
                "columns": [{"name": "period"}],
                "supported_filters": ["start_date", "end_date"],
                "coverage": None,
            }
        ],
    }
    services.catalog.describe.assert_called_once_with(
        access.require_catalog.return_value, services.encoding
    )
    access.authenticate.assert_called_once_with("session-token")
    access.require_catalog.assert_called_once_with(access.authenticate.return_value)
