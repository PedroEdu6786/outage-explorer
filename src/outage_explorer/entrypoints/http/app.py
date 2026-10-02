from flask import Flask

from outage_explorer.application.services.health import HealthService
from outage_explorer.entrypoints.http.routes.health import create_health_blueprint


def create_app(health_service: HealthService) -> Flask:
    """Register already-constructed services; do not perform runtime wiring."""
    app = Flask(__name__, static_folder=None)
    app.register_blueprint(create_health_blueprint(health_service))
    return app
