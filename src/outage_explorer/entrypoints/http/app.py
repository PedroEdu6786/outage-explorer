from flask import Flask, Response, request

from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.data_schemas import MAX_BODY_BYTES
from outage_explorer.entrypoints.http.data_services import DataServices
from outage_explorer.entrypoints.http.errors import register_auth_errors
from outage_explorer.entrypoints.http.routes.access import create_access_blueprint
from outage_explorer.entrypoints.http.routes.datasets import create_datasets_blueprint
from outage_explorer.entrypoints.http.routes.documentation import register_documentation
from outage_explorer.entrypoints.http.routes.health import create_health_blueprint
from outage_explorer.entrypoints.http.routes.queries import create_queries_blueprint
from outage_explorer.entrypoints.http.routes.refresh import create_refresh_blueprint


def create_app(
    health_service: HealthService,
    *,
    login_service: LoginService | None = None,
    access_service: AccessService | None = None,
    auth_transport: AuthTransport | None = None,
    data_services: DataServices | None = None,
) -> Flask:
    """Register already-constructed services; do not perform runtime wiring."""
    supplied = (
        login_service is not None,
        access_service is not None,
        auth_transport is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError("Incomplete authentication services")
    if data_services is not None and not all(supplied):
        raise ValueError("Data services require authentication services")
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_BODY_BYTES
    app.config["JSON_SORT_KEYS"] = False
    register_documentation(
        app,
        development_http=auth_transport.development_http if auth_transport else False,
    )
    app.register_blueprint(create_health_blueprint(health_service))
    if (
        login_service is not None
        and access_service is not None
        and auth_transport is not None
    ):
        register_auth_errors(app)
        app.register_blueprint(
            create_access_blueprint(login_service, access_service, auth_transport)
        )

        if data_services is not None:
            app.register_blueprint(
                create_datasets_blueprint(data_services, auth_transport)
            )
            app.register_blueprint(
                create_queries_blueprint(data_services, access_service, auth_transport)
            )
            app.register_blueprint(
                create_refresh_blueprint(data_services, access_service, auth_transport)
            )

        @app.after_request
        def auth_headers(response: Response) -> Response:
            if request.path.startswith(
                ("/api/auth/", "/api/datasets", "/api/query", "/api/refresh")
            ):
                return auth_transport.finalize(response)
            return response

    return app
