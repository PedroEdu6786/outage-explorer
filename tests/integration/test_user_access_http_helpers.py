"""Guards deny before handlers; downstream authorization remains independent."""

from dataclasses import replace
from datetime import timedelta

import pytest
from flask import Flask, Response

from outage_explorer.application.errors import ForbiddenError, UnauthenticatedError
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import AccessOperation, AnalyticalGrain, Role
from outage_explorer.entrypoints.http.auth_helpers import (
    authenticated,
    csrf_protected,
    validated_request,
)
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.errors import error_response
from outage_explorer.entrypoints.http.schemas import json_object, query_fields
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from tests.unit.test_user_access_sessions import Clock, Store

ORIGIN = "http://localhost:8000"


@pytest.fixture
def guarded_app():
    store, clock, security = Store(), Clock(), RandomSecurityMaterial()
    access = AccessService(store, security, clock)
    transport = AuthTransport(ORIGIN, frozenset({ORIGIN}), True)
    token = security.random_token()
    store.create_session(
        security.digest(token),
        store.user.id,
        clock.time,
        clock.time + timedelta(hours=1),
    )
    store.user = replace(store.user, role=Role.ANALYST)
    calls = []
    app = Flask(__name__)
    app.register_error_handler(Exception, error_response)

    def protected_use_case(credential):
        access.authorize(
            credential,
            AccessOperation.ANALYTICAL,
            grains=frozenset({AnalyticalGrain.FACILITY}),
        )
        calls.append("data")
        return Response("protected")

    @app.get("/read")
    @authenticated(access, transport)
    @validated_request(lambda: query_fields(frozenset({"mode"})))
    def read(*, credential, identity, validated):
        calls.append("handler")
        assert identity.user.role == Role.ANALYST
        if validated.get("mode") == "role":
            store.user = replace(store.user, role=Role.VIEWER)
        elif validated.get("mode") == "logout":
            access.logout(credential)
        elif validated.get("mode") == "expiry":
            clock.time += timedelta(hours=1)
        return protected_use_case(credential)

    @app.post("/write")
    @authenticated(access, transport)
    @csrf_protected(access, transport)
    @validated_request(
        lambda: json_object(frozenset({"value"}), required=frozenset({"value"}))
    )
    def write(*, credential, identity, csrf_validated, validated):
        assert csrf_validated and identity.user.role == Role.ANALYST
        assert validated == {"value": "ok"}
        calls.append("handler")
        return protected_use_case(credential)

    return (
        app,
        access,
        transport,
        token,
        security,
        store,
        clock,
        calls,
        protected_use_case,
    )


def client_with_cookie(harness):
    client = harness[0].test_client()
    client.set_cookie(harness[2].session_cookie, harness[3])
    return client


@pytest.mark.parametrize(
    "failure", ["missing", "malformed", "expired", "logged_out", "unknown", "store"]
)
def test_authentication_denies_before_handlers(guarded_app, failure):
    _, access, transport, token, _, store, clock, calls, _ = guarded_app
    client = client_with_cookie(guarded_app)
    if failure == "missing":
        client.delete_cookie(transport.session_cookie)
    elif failure == "malformed":
        client.set_cookie(transport.session_cookie, "SECRET")
    elif failure == "expired":
        clock.time += timedelta(hours=1)
    elif failure == "logged_out":
        access.logout(token)
    elif failure == "unknown":
        store.user = None
    else:
        store.failure = True
    response = client.get("/read")
    assert response.status_code == (503 if failure == "store" else 401)
    assert calls == []
    assert "protected" not in response.get_data(as_text=True)


def test_successful_typed_injection_and_composition(guarded_app):
    client = client_with_cookie(guarded_app)
    assert client.get("/read").status_code == 200
    response = client.post(
        "/write",
        json={"value": "ok"},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": guarded_app[4].csrf_token(guarded_app[3]),
        },
    )
    assert response.status_code == 200
    assert guarded_app[7] == ["handler", "data", "handler", "data"]


@pytest.mark.parametrize(
    "failure",
    [
        "origin",
        "missing_origin",
        "csrf",
        "other_session",
        "query",
        "json",
        "duplicate_json",
        "unsupported_json",
    ],
)
def test_csrf_and_validation_deny_before_work(guarded_app, failure):
    client = client_with_cookie(guarded_app)
    security, token, calls = guarded_app[4], guarded_app[3], guarded_app[7]
    headers = {"Origin": ORIGIN, "X-CSRF-Token": security.csrf_token(token)}
    if failure == "query":
        response = client.get("/read?mode=a&mode=b")
    else:
        if failure == "origin":
            headers["Origin"] = "https://evil.test"
        elif failure == "missing_origin":
            del headers["Origin"]
        elif failure == "csrf":
            headers["X-CSRF-Token"] = "SECRET"
        elif failure == "other_session":
            headers["X-CSRF-Token"] = security.csrf_token(security.random_token())
        body = {
            "json": '{"value":',
            "duplicate_json": '{"value":"ok","value":"SECRET"}',
            "unsupported_json": '{"value":"ok","role":"admin"}',
        }.get(failure, '{"value":"ok"}')
        response = client.post(
            "/write", data=body, content_type="application/json", headers=headers
        )
    assert response.status_code == (
        400
        if failure in {"query", "json", "duplicate_json", "unsupported_json"}
        else 403
    )
    assert calls == []
    assert "SECRET" not in response.get_data(as_text=True)


@pytest.mark.parametrize(
    "change,status", [("role", 403), ("logout", 401), ("expiry", 401)]
)
def test_stale_decorator_identity_cannot_grant_use_case_access(
    guarded_app, change, status
):
    response = client_with_cookie(guarded_app).get("/read?mode=" + change)
    assert response.status_code == status
    assert guarded_app[7] == ["handler"]
    assert "protected" not in response.get_data(as_text=True)


def test_direct_use_case_rechecks_role_and_session(guarded_app):
    _, access, _, token, _, store, _, calls, use_case = guarded_app
    store.user = replace(store.user, role=Role.VIEWER)
    with pytest.raises(ForbiddenError):
        use_case(token)
    access.logout(token)
    with pytest.raises(UnauthenticatedError):
        use_case(token)
    assert calls == []
