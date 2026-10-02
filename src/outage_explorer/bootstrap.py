"""Composition root: construct concrete dependencies only at startup."""

from flask import Flask

from outage_explorer.application.services.health import HealthService
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.infrastructure.clock import SystemClock


def build_http_app() -> Flask:
    return create_app(health_service=HealthService(clock=SystemClock()))
