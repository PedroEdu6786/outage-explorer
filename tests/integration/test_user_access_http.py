"""Flask transport with real application services and controlled ports."""

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from outage_explorer.application.errors import AccessConfigurationError
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.bootstrap import build_http_app
from outage_explorer.domain.access import Role
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import (
    AuthTransport,
    CallbackLogFilter,
)
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.settings import auth_settings
from tests.unit.test_user_access_sessions import Clock, Provider, Store

PUBLIC = "http://localhost:8000"
UI = "http://localhost:3000"
CONFIG = {
    "OUTAGE_AUTH_ENABLED": "true",
    "OUTAGE_ACCESS_DATABASE_DSN": "host=127.0.0.1 port=1 dbname=unused",
    "COGNITO_ISSUER": "https://cognito-idp.test/pool",
    "COGNITO_DOMAIN": "https://login.test",
    "COGNITO_APP_CLIENT_ID": "client",
    "COGNITO_OAUTH_SCOPES": "email",
    "OUTAGE_AUTH_PUBLIC_ORIGIN": PUBLIC,
    "OUTAGE_AUTH_CALLBACK_URI": PUBLIC + "/api/auth/callback",
    "OUTAGE_AUTH_UI_ORIGIN": UI,
    "OUTAGE_AUTH_DEVELOPMENT_HTTP": "true",
}


@pytest.fixture
def http_app():
    store, clock, security = Store(), Clock(), RandomSecurityMaterial()
    clock.time = datetime.now(UTC).replace(microsecond=0)
    provider = Provider(store)
    login = LoginService(
        provider,
        store,
        store,
        store,
        security,
        clock,
        callback_uri=PUBLIC + "/api/auth/callback",
        allowed_destinations=frozenset({"/", "/dashboard"}),
    )
    access = AccessService(store, security, clock)
    transport = AuthTransport(UI, frozenset({PUBLIC, UI}), True)
    app = create_app(
        HealthService(clock),
        login_service=login,
        access_service=access,
        auth_transport=transport,
    )
    return app, store, clock, provider, transport


def begin(client, *, return_to="/"):
    response = client.get("/api/auth/login", query_string={"return_to": return_to})
    assert response.status_code == 302
    state = parse_qs(urlsplit(response.location).query)["state"][0]
    return response, state


def sign_in(client):
    _, state = begin(client)
    response = client.get(
        "/api/auth/callback", query_string={"code": "CODE-SECRET", "state": state}
    )
    assert response.status_code == 302
    return response


def cookie(response, name):
    for value in response.headers.getlist("Set-Cookie"):
        parsed = SimpleCookie(value)
        if name in parsed:
            return parsed[name]
    raise AssertionError("Cookie missing")


def logout(client, csrf, *, origin=UI):
    return client.post(
        "/api/auth/logout", headers={"Origin": origin, "X-CSRF-Token": csrf}
    )


@pytest.mark.parametrize("role", list(Role))
def test_persona_login_current_role_and_absolute_cookie(http_app, role):
    app, store, clock, provider, transport = http_app
    store.user = replace(store.user, role=role)
    client = app.test_client()
    initial = clock.time
    redirect, state = begin(client, return_to="/dashboard")
    binding = cookie(redirect, transport.attempt_cookie)
    assert (
        binding["httponly"] and binding["samesite"] == "Lax" and not binding["domain"]
    )
    assert parsedate_to_datetime(binding["expires"]) == initial + timedelta(minutes=10)
    response = client.get(
        "/api/auth/callback", query_string={"code": "CODE-SECRET", "state": state}
    )
    assert response.location == UI + "/dashboard"
    session_cookie = cookie(response, transport.session_cookie)
    assert not session_cookie["secure"] and not session_cookie["domain"]
    assert (
        session_cookie["httponly"]
        and session_cookie["samesite"] == "Lax"
        and session_cookie["path"] == "/"
    )
    assert parsedate_to_datetime(session_cookie["expires"]) == initial + timedelta(
        hours=1
    )
    assert not session_cookie["max-age"]
    assert cookie(response, transport.attempt_cookie)["max-age"] == "0"
    identity = client.get("/api/auth/session")
    assert identity.json == {
        "user": {"id": "one", "email": "viewer@test", "role": role.value},
        "expires_at": (initial + timedelta(hours=1)).isoformat(),
        "csrf_token": identity.json["csrf_token"],
    }
    assert len(identity.json["csrf_token"]) == 64
    assert session_cookie.value not in identity.get_data(as_text=True)
    assert "issuer" not in identity.get_data(
        as_text=True
    ) and "subject" not in identity.get_data(as_text=True)
    assert identity.headers["Cache-Control"] == "no-store"
    clock.time += timedelta(minutes=30)
    assert (
        client.get("/api/auth/session").json["expires_at"]
        == identity.json["expires_at"]
    )
    assert "Set-Cookie" not in client.get("/api/auth/session").headers
    assert provider.calls == 1


def test_production_cookie_prefix_secure_and_host_only():
    store, clock, security = Store(), Clock(), RandomSecurityMaterial()
    clock.time = datetime.now(UTC).replace(microsecond=0)
    provider = Provider(store)
    access = AccessService(store, security, clock)
    login = LoginService(
        provider,
        store,
        store,
        store,
        security,
        clock,
        callback_uri="https://backend.test/api/auth/callback",
    )
    transport = AuthTransport(
        "https://ui.test", frozenset({"https://backend.test", "https://ui.test"})
    )
    client = create_app(
        HealthService(clock),
        login_service=login,
        access_service=access,
        auth_transport=transport,
    ).test_client()
    response = client.get("/api/auth/login", base_url="https://backend.test")
    state = parse_qs(urlsplit(response.location).query)["state"][0]
    assert cookie(response, "__Host-outage_login")["secure"]
    response = client.get(
        "/api/auth/callback",
        query_string={"code": "code", "state": state},
        base_url="https://backend.test",
    )
    value = cookie(response, "__Host-outage_session")
    assert (
        value["secure"]
        and value["httponly"]
        and value["path"] == "/"
        and not value["domain"]
    )


@pytest.mark.parametrize(
    "failure",
    [
        "state",
        "binding",
        "expiry",
        "provider",
        "unknown",
        "error",
        "duplicate",
        "empty",
    ],
)
def test_failed_callbacks_generic_no_session_no_store(http_app, failure):
    app, store, clock, provider, transport = http_app
    client = app.test_client()
    _, state = begin(client)
    query = {"code": "CODE-SECRET", "state": state}
    if failure == "state":
        query["state"] = "wrong"
    elif failure == "binding":
        client.set_cookie(transport.attempt_cookie, "wrong")
    elif failure == "expiry":
        clock.time += timedelta(minutes=10)
    elif failure == "provider":
        provider.failure = True
    elif failure == "unknown":
        store.user = None
    elif failure == "error":
        query = {
            "error": "RAW-PROVIDER-SECRET",
            "error_description": "RAW-PROVIDER-SECRET",
            "state": state,
        }
    elif failure == "duplicate":
        query = [("code", "CODE-SECRET"), ("code", "other"), ("state", state)]
    else:
        query["code"] = ""
    response = client.get("/api/auth/callback", query_string=query)
    assert response.status_code == 400
    assert response.json["error"]["code"] in {"login_failed", "invalid_request"}
    assert response.headers["Cache-Control"] == "no-store"
    assert "SECRET" not in response.get_data(as_text=True)
    assert cookie(response, transport.attempt_cookie)["max-age"] == "0"
    assert not store.sessions
    assert client.get("/api/auth/session").status_code == 401


def test_callback_single_use_replay_and_allowlisted_destinations(http_app):
    app, _, _, provider, _ = http_app
    client = app.test_client()
    for path in ("https://evil.test", "//evil.test", "/unknown", "/%2f/evil.test"):
        response = client.get("/api/auth/login", query_string={"return_to": path})
        assert response.status_code == 400 and "Location" not in response.headers
    _, state = begin(client)
    url = "/api/auth/callback?code=CODE-SECRET&state=" + state
    assert client.get(url).status_code == 302
    assert client.get(url).status_code == 400
    assert provider.calls == 1


def test_expiry_and_logout_replay_do_not_renew(http_app):
    app, _, clock, provider, transport = http_app
    client = app.test_client()
    sign_in(client)
    token = client.get_cookie(transport.session_cookie).value
    identity = client.get("/api/auth/session").json
    clock.time = datetime.fromisoformat(identity["expires_at"]) - timedelta(
        microseconds=1
    )
    assert client.get("/api/auth/session").status_code == 200
    clock.time += timedelta(microseconds=1)
    response = client.get("/api/auth/session")
    assert (
        response.status_code == 401
        and response.json["error"]["code"] == "unauthenticated"
    )
    assert provider.calls == 1
    assert logout(client, identity["csrf_token"]).status_code == 204
    client.set_cookie(transport.session_cookie, token)
    assert client.get("/api/auth/session").status_code == 401


@pytest.mark.parametrize(
    "origin,csrf",
    [
        (None, "valid"),
        ("null", "valid"),
        ("https://evil.test", "valid"),
        (UI + "/", "valid"),
        (UI, "wrong"),
        (UI, ""),
    ],
)
def test_logout_origin_csrf_denial_preserves_valid_session(http_app, origin, csrf):
    app, _, _, _, _ = http_app
    client = app.test_client()
    sign_in(client)
    identity = client.get("/api/auth/session").json
    supplied = identity["csrf_token"] if csrf == "valid" else csrf
    headers = {"X-CSRF-Token": supplied}
    if origin is not None:
        headers["Origin"] = origin
    response = client.post("/api/auth/logout", headers=headers)
    assert response.status_code == 403 and response.json == {
        "error": {"code": "forbidden", "message": "Access denied"}
    }
    assert (
        response.headers["Cache-Control"] == "no-store"
        and "Set-Cookie" not in response.headers
    )
    assert client.get("/api/auth/session").status_code == 200


def test_independent_logout_csrf_binding_idempotency_and_replay(http_app):
    app, _, _, provider, transport = http_app
    first, second = app.test_client(), app.test_client()
    sign_in(first)
    first_token = first.get_cookie(transport.session_cookie).value
    first_csrf = first.get("/api/auth/session").json["csrf_token"]
    sign_in(second)
    second_csrf = second.get("/api/auth/session").json["csrf_token"]
    assert logout(second, first_csrf).status_code == 403
    response = logout(first, first_csrf)
    assert response.status_code == 204 and response.data == b""
    assert cookie(response, transport.session_cookie)["max-age"] == "0"
    first.set_cookie(transport.session_cookie, first_token)
    assert first.get("/api/auth/session").status_code == 401
    assert logout(first, first_csrf).status_code == 204
    assert second.get("/api/auth/session").status_code == 200
    assert logout(second, second_csrf).status_code == 204
    assert provider.calls == 2


def test_database_failures_no_logout_success_or_cookie_clear(http_app):
    app, store, _, _, _ = http_app
    client = app.test_client()
    sign_in(client)
    csrf = client.get("/api/auth/session").json["csrf_token"]
    store.failure = True
    for response in (client.get("/api/auth/session"), logout(client, csrf)):
        assert (
            response.status_code == 503
            and response.json["error"]["code"] == "service_unavailable"
        )
        assert (
            response.headers["Cache-Control"] == "no-store"
            and "Set-Cookie" not in response.headers
        )
    store.failure = False
    with patch.object(
        store, "revoke_session", side_effect=RuntimeError("RAW-DATABASE-SECRET")
    ):
        response = logout(client, csrf)
    assert response.status_code == 503 and "SECRET" not in response.get_data(
        as_text=True
    )
    assert "Set-Cookie" not in response.headers
    assert client.get("/api/auth/session").status_code == 200


def test_credentialed_origins_preflight_and_sanitized_framework_errors(http_app):
    app, _, _, _, _ = http_app
    client = app.test_client()
    for origin in (UI, PUBLIC):
        response = client.options(
            "/api/auth/logout",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-CSRF-Token, Content-Type",
            },
        )
        assert response.status_code == 204
        assert response.headers["Access-Control-Allow-Origin"] == origin
        assert response.headers["Access-Control-Allow-Credentials"] == "true"
        assert "Origin" in response.headers["Vary"]
        assert response.headers["Cache-Control"] == "no-store"
    for origin, method, headers in (
        ("https://evil.test", "POST", "X-CSRF-Token"),
        (UI, "DELETE", "X-CSRF-Token"),
        (UI, "POST", "Authorization"),
    ):
        response = client.options(
            "/api/auth/logout",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": headers,
            },
        )
        assert response.status_code == 403
    response = client.get("/api/auth/session", headers={"Origin": "https://evil.test"})
    assert "Access-Control-Allow-Origin" not in response.headers
    for path in ("/api/auth/logout", "/api/auth/unknown"):
        response = client.get(path)
        assert (
            response.status_code == 400
            and response.json["error"]["code"] == "invalid_request"
        )
        assert response.headers["Cache-Control"] == "no-store"


def test_opt_in_configured_factory_inert_and_resource_cleanup(monkeypatch):
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)
    with (
        patch("httpx.Client.send", side_effect=AssertionError("Provider request")),
        patch("psycopg.connect", side_effect=AssertionError("Database connected")),
        patch("threading.Thread.start", side_effect=AssertionError("Thread started")),
        patch(
            "outage_explorer.bootstrap.run_migrations",
            side_effect=AssertionError("Migration ran"),
        ),
    ):
        app = build_http_app()
        assert app.test_client().get("/health").status_code == 200
    close = app.extensions["outage_access_close"]
    close()
    close()
    assert app.test_client().get("/api/auth/session").status_code == 401
    closed_client = app.test_client()
    closed_client.set_cookie("outage_session", "a" * 43)
    assert closed_client.get("/api/auth/session").status_code == 503


@pytest.mark.parametrize(
    "overrides",
    [
        {"OUTAGE_AUTH_ENABLED": "yes"},
        {"OUTAGE_AUTH_CALLBACK_URI": "https://evil.test/callback"},
        {"OUTAGE_AUTH_PUBLIC_ORIGIN": "http://remote.test"},
        {"OUTAGE_AUTH_PUBLIC_ORIGIN": PUBLIC + "/"},
        {"OUTAGE_AUTH_UI_ORIGIN": "https://user:pass@ui.test"},
        {"OUTAGE_AUTH_UI_ORIGIN": "https://ui.test?x=secret"},
        {"OUTAGE_AUTH_UI_ORIGIN": "https://ui.test"},
        {"OUTAGE_AUTH_UI_ORIGIN": "https://localhost "},
        {"OUTAGE_AUTH_UI_ORIGIN": "https://ui.test:99999"},
        {"OUTAGE_AUTH_DEVELOPMENT_HTTP": "false"},
        {"OUTAGE_AUTH_SESSION_SECONDS": "0"},
        {"OUTAGE_AUTH_ATTEMPT_SECONDS": "3601"},
        {"OUTAGE_AUTH_ATTEMPT_LIMIT": "100001"},
        {"OUTAGE_AUTH_RETURN_PATHS": "//evil.test"},
        {"OUTAGE_AUTH_RETURN_PATHS": "/%2f/evil.test"},
        {"COGNITO_OAUTH_SCOPES": ""},
    ],
)
def test_invalid_config_is_deterministic_and_secret_free(overrides):
    with pytest.raises(ValueError, match="^Invalid authentication configuration$"):
        auth_settings(CONFIG | overrides)


def test_missing_config_and_invalid_provider_fail_before_connections(monkeypatch):
    assert auth_settings({}) is None
    assert auth_settings(CONFIG).session_seconds == 3600
    assert auth_settings(CONFIG | {"OUTAGE_AUTH_UI_ORIGIN": ""}).ui_origin == PUBLIC
    assert CONFIG["OUTAGE_ACCESS_DATABASE_DSN"] not in repr(auth_settings(CONFIG))
    with pytest.raises(ValueError):
        auth_settings({"OUTAGE_AUTH_ENABLED": "true"})
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COGNITO_ISSUER", "http://bad.test")
    with (
        patch("httpx.Client", side_effect=AssertionError("Constructed provider")),
        patch("psycopg.connect", side_effect=AssertionError("Connected database")),
        pytest.raises(AccessConfigurationError),
    ):
        build_http_app()


def test_callback_access_log_queries_redacted():
    record = logging.LogRecord(
        "werkzeug",
        logging.INFO,
        "",
        0,
        "%s - %s",
        (
            "127.0.0.1",
            "GET /api/auth/callback?code=CODE-SECRET&state=STATE-SECRET HTTP/1.1",
        ),
        None,
    )
    assert CallbackLogFilter().filter(record)
    assert "SECRET" not in record.getMessage()
    assert "/api/auth/callback?[redacted]" in record.getMessage()


def test_malformed_provider_configuration_redacts_netloc(monkeypatch):
    for name, value in CONFIG.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("COGNITO_DOMAIN", "https://user:SECRET@bad／host")
    with (
        patch("httpx.Client", side_effect=AssertionError("Constructed client")),
        pytest.raises(AccessConfigurationError) as error,
    ):
        build_http_app()
    assert str(error.value) == "Invalid authentication configuration"
    assert "SECRET" not in str(error.value)
