from flask import Blueprint, Response, jsonify

from outage_explorer.application.services.health import HealthService


def create_health_blueprint(health_service: HealthService) -> Blueprint:
    blueprint = Blueprint("health", __name__)

    @blueprint.get("/health")
    def health() -> Response:
        result = health_service.check()
        response = jsonify(
            status=result.status,
            service=result.service,
            checked_at=result.checked_at.isoformat(),
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    return blueprint
