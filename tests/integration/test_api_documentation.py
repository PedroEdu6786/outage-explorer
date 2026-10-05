import json
import re
from pathlib import Path
from unittest.mock import Mock

from jsonschema import Draft202012Validator

from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_services import DataServices


def documented_app(*, development_http=False):
    return create_app(
        Mock(spec=HealthService),
        login_service=Mock(spec=LoginService),
        access_service=Mock(spec=AccessService),
        auth_transport=AuthTransport(
            "http://localhost:8000",
            frozenset({"http://localhost:8000"}),
            development_http,
        ),
        data_services=Mock(spec=DataServices),
    )


def test_documentation_is_available_without_optional_services():
    service = Mock(spec=HealthService)
    client = create_app(service).test_client()
    response = client.get("/api/docs", follow_redirects=True)
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    assert b"/api/openapi.json" in response.data
    assert b'"validatorUrl": null' in response.data
    assert b'"withCredentials": true' in response.data
    for asset in ("swagger-ui.css", "swagger-ui-bundle.js"):
        assert client.get("/api/docs/" + asset).status_code == 200
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["openapi"] == "3.1.0"
    service.check.assert_not_called()


def test_contract_covers_all_registered_product_and_documentation_operations():
    app = documented_app()
    contract = app.test_client().get("/api/openapi.json").json
    actual = set()
    for rule in app.url_map.iter_rules():
        # Swagger's catch-all serves distribution assets, not product operations.
        if rule.endpoint.startswith("swagger_ui."):
            continue
        path = re.sub(r"<([^>]+)>", r"{\1}", rule.rule)
        actual.update(
            (path, method.lower()) for method in rule.methods - {"HEAD", "OPTIONS"}
        )
    actual.add(("/api/docs", "get"))
    expected = {
        (path, method)
        for path, operations in contract["paths"].items()
        for method in operations
    }
    assert actual == expected
    ids = [
        operation["operationId"]
        for operations in contract["paths"].values()
        for operation in operations.values()
    ]
    assert len(ids) == len(set(ids)) == 14
    for schema in contract["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)


def test_documentation_preserves_the_existing_data_contract():
    source = json.loads(
        (Path(__file__).parents[2] / "docs/specs/data-api/openapi.json").read_text()
    )
    served = documented_app().test_client().get("/api/openapi.json").json
    for path, operations in source["paths"].items():
        for method, original in operations.items():
            current = served["paths"][path][method]
            assert {
                k: v for k, v in current.items() if k not in {"tags", "description"}
            } == {k: v for k, v in original.items() if k not in {"tags", "description"}}
    for name, schema in source["components"]["schemas"].items():
        assert served["components"]["schemas"][name] == schema


def test_local_cookie_names_are_instance_specific():
    local = documented_app(development_http=True).test_client()
    production = documented_app().test_client()
    assert (
        local.get("/api/openapi.json").json["components"]["securitySchemes"][
            "SessionCookie"
        ]["name"]
        == "outage_session"
    )
    assert (
        production.get("/api/openapi.json").json["components"]["securitySchemes"][
            "SessionCookie"
        ]["name"]
        == "__Host-outage_session"
    )
    cookies = [
        p["name"]
        for p in local.get("/api/openapi.json").json["paths"]["/api/auth/callback"][
            "get"
        ]["parameters"]
        if p["in"] == "cookie"
    ]
    assert cookies == ["outage_login"]
