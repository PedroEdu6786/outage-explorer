"""Composition root: construct concrete dependencies only at startup."""

import os
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import httpx
from flask import Flask

from outage_explorer.application.dto import (
    ConnectorInput,
    ConnectorRequest,
    ConnectorResult,
)
from outage_explorer.application.errors import ConnectorConfigurationError
from outage_explorer.application.ports.artifacts import ArtifactBounds, StoredObject
from outage_explorer.application.ports.source import SourceBounds
from outage_explorer.application.services.connector import CreateConnectorCandidate
from outage_explorer.application.services.evidence import (
    VerifyBaseline,
    VerifyNationalBaseline,
)
from outage_explorer.application.services.health import HealthService
from outage_explorer.domain.refresh import Interval, RefreshBounds
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.connector_report import LocalConnectorReports
from outage_explorer.infrastructure.eia.source import EiaSource
from outage_explorer.infrastructure.parquet.candidates import ParquetCandidateBuilder
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.recorded_evidence import LocalRecordedEvidence
from outage_explorer.infrastructure.verification_report import LocalReportWriter
from outage_explorer.settings import connector_settings


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


def execute_connector(
    inputs: ConnectorInput,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ConnectorResult:
    """Validate before construction; own and close even an injected transport."""
    try:
        config = connector_settings(
            inputs.start,
            inputs.end,
            inputs.staging,
            inputs.prior,
            os.environ if environment is None else environment,
            inputs.config_path,
        )
        source_bounds = SourceBounds(**asdict(config.source))
        artifact_bounds = ArtifactBounds(**asdict(config.artifact))
        model_bounds = RefreshBounds(**asdict(config.model))
        interval = Interval(config.start, config.end)
        if (interval.end - interval.start).days + 1 > min(
            source_bounds.interval_days, model_bounds.interval_days
        ):
            raise ValueError
        prior = (
            None
            if config.prior_digest is None or config.prior_bytes is None
            else StoredObject(
                config.prior_digest, config.prior_digest, config.prior_bytes
            )
        )
        if prior is not None and prior.byte_count > artifact_bounds.file_bytes:
            raise ValueError
        # Fixed/generated identities must fit before storage or transport exists.
        if model_bounds.field_chars < 64 or source_bounds.field_bytes < 64:
            raise ValueError
    except (ValueError, TypeError):
        if transport is not None:
            transport.close()
        raise ConnectorConfigurationError("Invalid connector configuration") from None
    run_id, generation_id = uuid4().hex, uuid4().hex
    request = ConnectorRequest(interval, run_id, generation_id, model_bounds, prior)
    wire = transport
    try:
        root = Path(config.staging)
        store = LocalParquetStore(root / "objects", artifact_bounds)
        reports = LocalConnectorReports(root, run_id, config.report_bytes)
        if wire is None:
            wire = httpx.HTTPTransport(retries=0, trust_env=False)
        source_transport = wire
        service = CreateConnectorCandidate(
            lambda source_request: EiaSource(
                source_request, source_bounds, source_transport, config.api_key
            ),
            LocalConnectorEvidence(store),
            ParquetCandidateBuilder(store),
            reports,
        )
        return service.run(request)
    finally:
        if wire is not None:
            wire.close()
