"""Composition root: construct concrete dependencies only at startup."""

from flask import Flask

from outage_explorer.application.services.evidence import (
    VerifyBaseline,
    VerifyNationalBaseline,
)
from outage_explorer.application.services.health import HealthService
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.recorded_evidence import LocalRecordedEvidence
from outage_explorer.infrastructure.verification_report import LocalReportWriter


def build_http_app() -> Flask:
    return create_app(health_service=HealthService(clock=SystemClock()))


def build_national_verifier() -> VerifyNationalBaseline:
    return VerifyNationalBaseline(LocalRecordedEvidence(), LocalReportWriter())


def build_facility_verifier() -> VerifyBaseline:
    return VerifyBaseline(
        LocalRecordedEvidence("facility"), LocalReportWriter(), "facility"
    )


def build_generator_verifier() -> VerifyBaseline:
    return VerifyBaseline(
        LocalRecordedEvidence("generator"), LocalReportWriter(), "generator"
    )
