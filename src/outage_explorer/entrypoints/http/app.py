from flask import Flask, Response, request

from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.entrypoints.http.auth_transport import AuthTransport
from outage_explorer.entrypoints.http.errors import register_auth_errors
from outage_explorer.entrypoints.http.routes.access import create_access_blueprint
from outage_explorer.entrypoints.http.routes.health import create_health_blueprint


def create_app(
    health_service: HealthService,
    *,
    login_service: LoginService | None = None,
    access_service: AccessService | None = None,
    auth_transport: AuthTransport | None = None,
) -> Flask:
    """Register already-constructed services; do not perform runtime wiring."""
    supplied = (
        login_service is not None,
        access_service is not None,
        auth_transport is not None,
    )
    if any(supplied) and not all(supplied):
        raise ValueError("Incomplete authentication services")
    app = Flask(__name__, static_folder=None)
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

        @app.after_request
        def auth_headers(response: Response) -> Response:
            if request.path.startswith("/api/auth/"):
                return auth_transport.finalize(response)
            return response

    return app
