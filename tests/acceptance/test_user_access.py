"""Independent PostgreSQL/provider/HTTP/direct-use-case acceptance."""

from datetime import timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import pytest

from outage_explorer.application.errors import (
    AccessStoreError,
    ForbiddenError,
    UnauthenticatedError,
)
from outage_explorer.domain.access import AccessOperation, AnalyticalGrain, Role
from outage_explorer.entrypoints.http.auth_helpers import authenticated
from outage_explorer.entrypoints.http.auth_transport import AuthTransport

pytestmark = pytest.mark.acceptance


def sign_in(harness, role="viewer", client=None):
    client = client or harness.app.test_client()
    response = client.get("/api/auth/login")
    state = parse_qs(urlsplit(response.location).query)["state"][0]
    response = client.get(
        "/api/auth/callback", query_string={"code": role, "state": state}
    )
    return client, response


@pytest.mark.parametrize("role", list(Role))
def test_each_seeded_persona_real_store_verified_provider_and_fixed_lease(
    harness, role
):
    started = harness.clock.time
    client, response = sign_in(harness, role.value)
    assert response.status_code == 302
    identity = client.get("/api/auth/session").json
    assert identity["user"]["role"] == role.value
    assert identity["expires_at"] == (started + timedelta(hours=1)).isoformat()
    token = client.get_cookie("outage_session").value
    protected_work = []

    def use_case(grain, page):
        decision = harness.access.authorize(
            token, AccessOperation.ANALYTICAL, grains=frozenset({grain})
        )
        protected_work.append((decision.principal.role, grain, page))

    for grain in AnalyticalGrain:
        for page in (1, 2):
            if role is Role.VIEWER and grain is not AnalyticalGrain.NATIONAL:
                with pytest.raises(ForbiddenError):
                    use_case(grain, page)
            else:
                use_case(grain, page)
    for operation in (
        AccessOperation.REFRESH_INITIATE,
        AccessOperation.REFRESH_OUTCOME,
        AccessOperation.REFRESH_DIAGNOSTIC,
    ):
        if role is Role.ADMIN:
            harness.access.authorize(token, operation)
        else:
            with pytest.raises(ForbiddenError):
                harness.access.authorize(token, operation)
    assert len(protected_work) == (2 if role is Role.VIEWER else 6)
    harness.clock.time += timedelta(minutes=50)
    assert client.get("/api/auth/session").json["expires_at"] == identity["expires_at"]
    assert len([r for r in harness.calls if r.method == "POST"]) == 1
    harness.clock.time = started + timedelta(hours=1)
    assert client.get("/api/auth/session").status_code == 401
    with pytest.raises(UnauthenticatedError):
        use_case(AnalyticalGrain.NATIONAL, 3)


def test_unknown_and_invalid_login_generic_failure_without_local_session(harness):
    for code in ("unknown", "invalid"):
        client, response = sign_in(harness, code)
        assert response.status_code == 400
        assert response.json == {
            "error": {"code": "login_failed", "message": "Login failed"}
        }
        assert client.get_cookie("outage_session") is None
    with harness.pool.connection() as connection:
        assert (
            connection.execute(
                "SELECT count(*) AS n FROM application_sessions"
            ).fetchone()["n"]
            == 0
        )


def test_independent_logout_replay_and_store_failure_deny_before_work(harness):
    first, _ = sign_in(harness)
    second, _ = sign_in(harness)
    first_token = first.get_cookie("outage_session").value
    csrf = first.get("/api/auth/session").json["csrf_token"]
    assert (
        first.post(
            "/api/auth/logout", headers={"Origin": harness.origin, "X-CSRF-Token": csrf}
        ).status_code
        == 204
    )
    first.set_cookie("outage_session", first_token)
    assert first.get("/api/auth/session").status_code == 401
    assert second.get("/api/auth/session").status_code == 200
    with patch.object(
        harness.store,
        "resolve_session",
        side_effect=AccessStoreError("Store unavailable"),
    ):
        assert second.get("/api/auth/session").status_code == 503
        with pytest.raises(AccessStoreError):
            harness.access.authorize(
                second.get_cookie("outage_session").value,
                AccessOperation.ANALYTICAL,
                grains=frozenset({AnalyticalGrain.NATIONAL}),
            )


def test_helper_result_cannot_replace_later_fresh_use_case_role_check(harness):
    client, _ = sign_in(harness, "admin")
    token = client.get_cookie("outage_session").value
    # HTTP acceptance above exercises current identity. A retained result is
    # deliberately kept while the trusted PostgreSQL role changes.
    stale = harness.access.current_identity(token)
    assert stale.user.role is Role.ADMIN
    captured = []

    @authenticated(
        harness.access, AuthTransport(harness.origin, frozenset({harness.origin}), True)
    )
    def use_case(*, credential, identity):
        captured.append(identity.user.role)
        with harness.pool.connection() as connection:
            connection.execute(
                "UPDATE users SET role_code = 'viewer' WHERE identity_subject = 'admin'"
            )
        harness.access.authorize(
            credential,
            AccessOperation.ANALYTICAL,
            grains=frozenset({AnalyticalGrain.FACILITY}),
        )
        pytest.fail("Protected work ran after role change")

    with harness.app.test_request_context(
        "/controlled", headers={"Cookie": "outage_session=" + token}
    ):
        with pytest.raises(ForbiddenError):
            use_case()
    assert captured == [Role.ADMIN]
    protected = []
    for page in (1, 2):
        with pytest.raises(ForbiddenError):
            harness.access.authorize(
                token,
                AccessOperation.ANALYTICAL,
                grains=frozenset({AnalyticalGrain.FACILITY}),
            )
            protected.append(page)
    assert protected == []


def test_existing_connection_checkout_does_not_sign_or_change_lease(
    harness, monkeypatch
):
    client, _ = sign_in(harness)
    original = client.get("/api/auth/session").json["expires_at"]
    monkeypatch.setattr(
        harness.pool,
        "_password_provider",
        lambda: pytest.fail("Existing checkout signed"),
    )
    for _ in range(3):
        assert client.get("/api/auth/session").json["expires_at"] == original
    assert len([r for r in harness.calls if r.method == "POST"]) == 1


def test_controlled_iam_reconnect_after_15_minutes_does_not_renew_app_or_provider(
    harness_factory,
):
    harness = harness_factory(iam=True)
    client, _ = sign_in(harness)
    original = client.get("/api/auth/session").json["expires_at"]
    initial_signatures = len(harness.signatures)
    harness.clock.time += timedelta(seconds=901)
    with harness.pool.connection() as connection:
        connection.close()
    assert client.get("/api/auth/session").json["expires_at"] == original
    assert len(harness.signatures) > initial_signatures
    assert (
        len(harness.signatures)
        == harness.pool._get_pool().get_stats()["connections_num"]
    )
    assert len([r for r in harness.calls if r.method == "POST"]) == 1
