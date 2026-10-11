"""Real controller guards with in-memory sessions; no analytical infrastructure."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import Role, SeededUser, Session
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_services import DataServices
from tests.integration.test_data_api_http import ORIGIN


@pytest.fixture
def preview_http():
    token = "a" * 43
    now = datetime.now(UTC)
    sessions, security, clock = Mock(), Mock(), Mock()
    clock.now.return_value = now
    security.digest.return_value = token
    user = SeededUser("reader", "issuer", "subject", "test@example.com", Role.ANALYST)
    sessions.resolve_session.return_value = Session(
        token, user, now, now + timedelta(hours=1)
    )
    access = AccessService(sessions, security, clock)
    services = DataServices(Mock(), Mock(), Mock(), Mock(), Mock())
    services.preview.read.return_value = {"rows": []}
    transport = AuthTransport(ORIGIN, frozenset({ORIGIN}), True)
    app = create_app(
        Mock(),
        login_service=Mock(),
        access_service=access,
        auth_transport=transport,
        data_services=services,
    )
    client = app.test_client()
    # Same cookie used by the existing login transport.
    client.set_cookie(transport.session_cookie, token)
    return client, sessions, services


def test_preview_guard_resolves_once_and_passes_validated_context(preview_http):
    client, sessions, services = preview_http
    response = client.get("/api/datasets/facilities/preview?facility=001&page_size=2")
    assert response.status_code == 200
    sessions.resolve_session.assert_called_once()
    access, request = services.preview.read.call_args.args
    assert access.principal.id == "reader" and access.dataset.id == "facilities"
    assert request.facility == "001" and request.size == 2


@pytest.mark.parametrize("dataset", ["facilities", "generators", "unknown"])
def test_guard_hides_forbidden_and_unknown_before_parsing(preview_http, dataset):
    client, sessions, services = preview_http
    session = sessions.resolve_session.return_value
    sessions.resolve_session.return_value = replace(
        session, user=replace(session.user, role=Role.VIEWER)
    )
    response = client.get(f"/api/datasets/{dataset}/preview?page_size=bad")
    assert response.status_code == 404
    assert response.json["error"]["code"] == "dataset_unavailable"
    services.preview.read.assert_not_called()
    sessions.resolve_session.assert_called_once()


def test_continuation_observes_role_change_and_revocation(preview_http):
    client, sessions, services = preview_http
    assert client.get("/api/datasets/facilities/preview").status_code == 200
    session = sessions.resolve_session.return_value
    sessions.resolve_session.return_value = replace(
        session, user=replace(session.user, role=Role.VIEWER)
    )
    assert (
        client.get("/api/datasets/facilities/preview?cursor=opaque").status_code == 404
    )
    sessions.resolve_session.return_value = None
    assert client.get("/api/datasets/national/preview?page_size=bad").status_code == 401
    assert services.preview.read.call_count == 1
    assert sessions.resolve_session.call_count == 3
