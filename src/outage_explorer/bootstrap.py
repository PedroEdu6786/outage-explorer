"""Composition root: construct concrete dependencies only at startup."""

import atexit
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3  # type: ignore[import-untyped]
import httpx
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import (  # type: ignore[import-untyped]
    MissingDependencyException,
)
from flask import Flask

from outage_explorer.application.dto import (
    AccessSetupInput,
    ConnectorArtifactInput,
    ConnectorInput,
    ConnectorRequest,
    ConnectorResult,
)
from outage_explorer.application.errors import (
    AccessConfigurationError,
    ConnectorConfigurationError,
    ConnectorDependencyError,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    StoredObject,
    TransferBounds,
)
from outage_explorer.application.ports.connector import DurableConnectorReceipt
from outage_explorer.application.ports.source import ROUTES, SourceBounds
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.connector import CreateConnectorCandidate
from outage_explorer.application.services.connector_artifacts import (
    CreateDurableConnectorCandidate,
    DurableCandidateResult,
    PersistConnectorArtifacts,
    RecoverConnectorArtifacts,
)
from outage_explorer.application.services.evidence import (
    VerifyBaseline,
    VerifyNationalBaseline,
)
from outage_explorer.application.services.health import HealthService
from outage_explorer.application.services.login import LoginService
from outage_explorer.application.services.seed_users import (
    SeedUsers,
    validate_identities,
)
from outage_explorer.domain.refresh import Interval, RefreshBounds
from outage_explorer.entrypoints.cli.access_setup import read_manifest
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import (
    AuthTransport,
    CallbackLogFilter,
)
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.cognito.identity import (
    CognitoConfig,
    CognitoIdentityProvider,
)
from outage_explorer.infrastructure.connector_events import LoggingConnectorEvents
from outage_explorer.infrastructure.connector_report import LocalConnectorReports
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.eia.budget import SourceRunBudget
from outage_explorer.infrastructure.eia.source import EiaSource
from outage_explorer.infrastructure.parquet.candidates import ParquetCandidateBuilder
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.postgresql.access import PostgresqlAccessStore
from outage_explorer.infrastructure.postgresql.credentials import (
    IAMCredentials,
    IAMTarget,
)
from outage_explorer.infrastructure.postgresql.migrations import run_migrations
from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.recorded_evidence import LocalRecordedEvidence
from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.infrastructure.verification_report import LocalReportWriter
from outage_explorer.settings import (
    DatabaseSettings,
    artifact_settings,
    auth_settings,
    connector_settings,
    database_settings,
    s3_settings,
)


def build_http_app() -> Flask:
    clock = SystemClock()
    try:
        settings = auth_settings(os.environ)
    except ValueError:
        raise AccessConfigurationError("Invalid authentication configuration") from None
    if settings is None:
        return create_app(health_service=HealthService(clock=clock))
    try:
        config = CognitoConfig(
            settings.issuer,
            settings.provider_domain,
            settings.client_id,
            settings.scopes,
            resource=settings.resource,
            client_secret=settings.client_secret,
        )
        pool = _access_pool(settings.database or database_settings(os.environ))
    except (ValueError, TypeError):
        raise AccessConfigurationError("Invalid authentication configuration") from None
    provider = CognitoIdentityProvider(config)
    access_logger = logging.getLogger("werkzeug")
    access_filter = CallbackLogFilter()
    access_logger.addFilter(access_filter)
    owner = os.getpid()
    closed = False

    def close() -> None:
        nonlocal closed
        if os.getpid() == owner and not closed:
            closed = True
            try:
                provider.close()
            finally:
                pool.close()
                access_logger.removeFilter(access_filter)
                atexit.unregister(close)

    try:
        store = PostgresqlAccessStore(pool, attempt_limit=settings.attempt_limit)
        security = RandomSecurityMaterial()
        login = LoginService(
            provider,
            store,
            store,
            store,
            security,
            clock,
            callback_uri=settings.callback_uri,
            allowed_destinations=settings.return_paths,
            session_seconds=settings.session_seconds,
            attempt_seconds=settings.attempt_seconds,
        )
        access = AccessService(store, security, clock)
        transport = AuthTransport(
            settings.ui_origin,
            frozenset({settings.public_origin, settings.ui_origin}),
            settings.development_http,
        )
        app = create_app(
            health_service=HealthService(clock=clock),
            login_service=login,
            access_service=access,
            auth_transport=transport,
        )
    except Exception:
        close()
        raise
    app.extensions["outage_access_close"] = close
    atexit.register(close)
    return app


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
            inputs.fetch_workers,
            inputs.s3_workers,
        )
        source_bounds = SourceBounds(**asdict(config.source))
        artifact_bounds = ArtifactBounds(**asdict(config.artifact))
        model_bounds = RefreshBounds(**asdict(config.model))
        interval = Interval(config.start, config.end)
        if (interval.end - interval.start).days + 1 > min(
            source_bounds.interval_days, model_bounds.interval_days
        ):
            raise ValueError
        # Admission bounds logical buffers before any transport/storage allocation.
        if (
            config.workers.endpoint_workers
            * config.workers.page_workers
            * (
                2 * artifact_bounds.file_bytes
                + 3 * artifact_bounds.row_group_bytes
                + source_bounds.response_bytes
                + source_bounds.output_bytes
            )
            > config.workers.memory_bytes
            or artifact_bounds.total_bytes > config.workers.temporary_bytes
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
    workers = BoundedConnectorWorkers(
        config.workers.endpoint_workers, elapsed_seconds=source_bounds.elapsed_seconds
    )
    budget = SourceRunBudget(source_bounds, workers.cancelled)
    endpoint_transports: list[httpx.BaseTransport] = []
    try:
        root = Path(config.staging)
        store = LocalParquetStore(root / "objects", artifact_bounds, workers.check)
        reports = LocalConnectorReports(root, run_id, config.report_bytes)
        if wire is None:
            wire = httpx.HTTPTransport(retries=0, trust_env=False)
        source_transport = wire
        # Default concurrent endpoints own separate pools. Controlled injection
        # explicitly supplies a worker-safe shared transport and is closed once.
        if transport is None and config.workers.endpoint_workers > 1:
            endpoint_transports = [source_transport]
            for _ in range(2):
                endpoint_transports.append(
                    httpx.HTTPTransport(retries=0, trust_env=False)
                )
        source_transports = (
            dict(zip(ROUTES, endpoint_transports, strict=True))
            if endpoint_transports
            else dict.fromkeys(ROUTES, source_transport)
        )
        service = CreateConnectorCandidate(
            lambda source_request: EiaSource(
                source_request,
                source_bounds,
                source_transports[source_request.grain],
                config.api_key,
                budget=budget,
                page_workers=config.workers.page_workers,
            ),
            LocalConnectorEvidence(store),
            ParquetCandidateBuilder(store),
            reports,
            LoggingConnectorEvents(),
            workers,
        )
        return service.run(request)
    finally:
        for endpoint_transport in endpoint_transports[1:]:
            endpoint_transport.close()
        if wire is not None:
            wire.close()


def execute_connector_artifacts(
    inputs: ConnectorArtifactInput,
    *,
    environment: Mapping[str, str] | None = None,
    session_factory: Callable[..., Any] | None = None,
    client: Any = None,
) -> DurableConnectorReceipt:
    """Explicit AWS operation; an injected session owns credential resolution."""
    try:
        root_text, digest, size, artifacts, model, s3, worker_config = (
            artifact_settings(
                inputs.staging,
                inputs.manifest,
                os.environ if environment is None else environment,
                inputs.config_path,
                inputs.s3_workers,
            )
        )
        artifact_bounds = ArtifactBounds(**asdict(artifacts))
        model_bounds = RefreshBounds(**asdict(model))
        reference = StoredObject(digest, digest, size)
        if inputs.operation not in ("persist", "recover"):
            raise ValueError
        root = Path(root_text)
        if inputs.operation == "recover" and root.exists() and any(root.iterdir()):
            raise ValueError
        if inputs.operation == "persist" and not (root / "objects").is_dir():
            raise ValueError
    except (ValueError, TypeError, OSError):
        raise ConnectorConfigurationError(
            "Invalid connector artifact configuration"
        ) from None
    transfer_bounds = replace(
        TransferBounds(), temporary_bytes=worker_config.temporary_bytes
    )
    if (
        worker_config.s3_workers
        * (2 * artifact_bounds.file_bytes + artifact_bounds.row_group_bytes)
        > worker_config.memory_bytes
        or 2 * artifact_bounds.total_bytes
        + worker_config.s3_workers * artifact_bounds.file_bytes
        > worker_config.temporary_bytes
    ):
        raise ConnectorConfigurationError("Invalid connector artifact worker limits")
    workers = BoundedConnectorWorkers(
        worker_config.s3_workers, elapsed_seconds=transfer_bounds.elapsed_seconds
    )
    local = LocalConnectorEvidence(
        LocalParquetStore(root / "objects", artifact_bounds, workers.check), workers
    )
    # Verify the complete local candidate before constructing an AWS client.
    if inputs.operation == "persist":
        local.graph(reference, model_bounds)
    wire = client
    owned = wire is None
    try:
        if wire is None:
            provider = boto3.Session if session_factory is None else session_factory
            session = provider(profile_name=s3.profile, region_name=s3.region)
            wire = session.client(
                "s3",
                config=Config(
                    connect_timeout=transfer_bounds.timeout_seconds,
                    read_timeout=transfer_bounds.timeout_seconds,
                    retries={"mode": "standard", "total_max_attempts": 1},
                    max_pool_connections=worker_config.s3_workers,
                ),
            )
        durable = S3ArtifactStore(
            wire,
            s3.bucket,
            s3.prefix,
            artifact_bounds,
            transfer_bounds,
            cancelled=workers.cancelled,
        )
        if inputs.operation == "persist":
            return PersistConnectorArtifacts(
                local, durable, LoggingConnectorEvents(), workers
            ).execute(reference, model_bounds)
        RecoverConnectorArtifacts(local, durable, LoggingConnectorEvents()).execute(
            reference, model_bounds
        )
        graph = local.graph(reference, model_bounds)
        return DurableConnectorReceipt(
            reference, len(graph), sum(item.byte_count for item in graph)
        )
    except MissingDependencyException:
        raise ConnectorDependencyError("AWS SDK login dependency unavailable") from None
    finally:
        if owned and wire is not None:
            wire.close()


def execute_connector_to_s3(
    inputs: ConnectorInput,
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    session_factory: Callable[..., Any] | None = None,
    client: Any = None,
) -> DurableCandidateResult:
    """Validate durable configuration before source work; compose existing use cases."""
    env = os.environ if environment is None else environment
    try:
        s3_settings(env)
    except ValueError:
        if transport is not None:
            transport.close()
        raise ConnectorConfigurationError(
            "Invalid connector S3 configuration"
        ) from None
    service = CreateDurableConnectorCandidate(
        lambda request: execute_connector(
            request, environment=env, transport=transport
        ),
        lambda request: execute_connector_artifacts(
            request, environment=env, session_factory=session_factory, client=client
        ),
        LoggingConnectorEvents(),
    )
    return service.execute(inputs)


def execute_access_setup(inputs: AccessSetupInput) -> int | tuple[int, int] | None:
    """Connect only on explicit operator command; never migrate during startup."""
    try:
        database = database_settings(os.environ)
    except ValueError:
        raise AccessConfigurationError("Invalid PostgreSQL configuration") from None
    identities = None
    if inputs.operation == "seed":
        if inputs.manifest is None:
            raise AccessConfigurationError("Seed manifest required")
        identities = read_manifest(inputs.manifest)
        validate_identities(identities)
    elif inputs.operation == "migrate":
        credentials = _access_credentials(database)
        run_migrations(
            database.dsn, password_provider=credentials.token if credentials else None
        )
        return None
    elif inputs.operation != "cleanup":
        raise AccessConfigurationError("Invalid setup operation")
    pool = _access_pool(database)
    try:
        store = PostgresqlAccessStore(pool)
        if identities is not None:
            return SeedUsers(store).execute(identities)
        return store.cleanup(SystemClock().now())
    finally:
        pool.close()


def _access_credentials(database: DatabaseSettings) -> IAMCredentials | None:
    if database.mode != "iam":
        return None
    return IAMCredentials(
        IAMTarget(
            database.host,
            database.port,
            database.user,
            database.region,
            database.profile,
        )
    )


def _access_pool(database: DatabaseSettings) -> BoundedPostgresqlPool:
    credentials = _access_credentials(database)
    return BoundedPostgresqlPool(
        database.dsn, password_provider=credentials.token if credentials else None
    )
