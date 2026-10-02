from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from flask.cli import ScriptInfo

from outage_explorer.application.dto import HealthStatus
from outage_explorer.application.services.health import HealthService
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.startup import create_app as start_app


def test_http_contract_and_injected_service():
    service = Mock(spec=HealthService)
    service.check.return_value = HealthStatus(datetime(2026, 10, 1, tzinfo=UTC))
    app = create_app(service)
    service.check.assert_not_called()

    response = app.test_client().get("/health")

    assert response.status_code == 200
    assert response.content_type == "application/json"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json == {
        "status": "ok",
        "service": "outage-explorer",
        "checked_at": "2026-10-01T00:00:00+00:00",
    }
    service.check.assert_called_once_with()


def test_instances_keep_their_own_dependencies():
    first = Mock(spec=HealthService)
    second = Mock(spec=HealthService)
    first.check.return_value = HealthStatus(datetime(2026, 10, 1, tzinfo=UTC))
    second.check.return_value = HealthStatus(datetime(2026, 10, 2, tzinfo=UTC))
    first_client = create_app(first).test_client()
    second_client = create_app(second).test_client()

    assert first_client.get("/health").json["checked_at"].startswith("2026-10-01")
    assert second_client.get("/health").json["checked_at"].startswith("2026-10-02")
    assert first_client.get("/health").json["checked_at"].startswith("2026-10-01")


def test_real_startup_and_clock_without_external_configuration(monkeypatch):
    for name in (
        "DATABASE_URL",
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "EIA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    before = datetime.now(UTC)
    response = start_app().test_client().get("/health")
    after = datetime.now(UTC)

    assert response.status_code == 200
    checked_at = datetime.fromisoformat(response.json["checked_at"])
    assert checked_at.tzinfo == UTC
    assert before <= checked_at <= after


def test_documented_flask_cli_factory_loads():
    app = ScriptInfo(
        app_import_path="outage_explorer.entrypoints.http.startup:create_app"
    ).load_app()
    assert app.test_client().get("/health").status_code == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_health_is_read_only(method):
    assert start_app().test_client().open("/health", method=method).status_code == 405


def test_unknown_route_and_head():
    client = start_app().test_client()
    assert client.get("/missing").status_code == 404
    response = client.head("/health")
    assert response.status_code == 200
    assert response.data == b""
