"""Composition root: construct concrete dependencies only at startup."""

import atexit
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
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
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import PublishedInputs
from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    StoredObject,
    TransferBounds,
)
from outage_explorer.application.ports.connector import DurableConnectorReceipt
from outage_explorer.application.ports.execution import (
    IsolatedExecution,
)
from outage_explorer.application.ports.preview_sequences import PreviewSequences
from outage_explorer.application.ports.query_results import QueryResults
from outage_explorer.application.ports.refresh_execution import RefreshConnector
from outage_explorer.application.ports.source import ROUTES, SourceBounds
from outage_explorer.application.ports.sql_inspection import SqlInspector
from outage_explorer.application.ports.tabular_encoding import TabularEncoding
from outage_explorer.application.services.access import AccessService
from outage_explorer.application.services.catalog import CatalogService
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
from outage_explorer.application.services.preview import PreviewService
from outage_explorer.application.services.queries import QueryService
from outage_explorer.application.services.refresh import RefreshService
from outage_explorer.application.services.refresh_execution import (
    RefreshExecution,
    RefreshReports,
    RefreshWorker,
)
from outage_explorer.application.services.seed_users import (
    SeedUsers,
    validate_identities,
)
from outage_explorer.domain.publication import (
    RefreshConfiguration,
    RefreshOwner,
    RefreshRun,
)
from outage_explorer.domain.refresh import Interval, RefreshBounds
from outage_explorer.entrypoints.cli.access_setup import read_manifest
from outage_explorer.entrypoints.http.app import create_app
from outage_explorer.entrypoints.http.auth_transport import (
    AuthTransport,
    CallbackLogFilter,
)
from outage_explorer.entrypoints.http.data_services import DataServices
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
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlPublicationStore,
)
from outage_explorer.infrastructure.query_results.cleanup import QueryCleanup
from outage_explorer.infrastructure.query_results.encoding import EncodingBounds
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.query_results.store import (
    BoundedQueryResults,
    ResultBounds,
)
from outage_explorer.infrastructure.recorded_evidence import LocalRecordedEvidence
from outage_explorer.infrastructure.refresh_worker import (
    RenewableRefreshLease,
    SupervisedRefreshProcess,
)
from outage_explorer.infrastructure.s3.artifacts import S3ArtifactStore
from outage_explorer.infrastructure.security import RandomSecurityMaterial
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
    SubprocessSqlInspector,
    UnavailableSqlInspector,
)
from outage_explorer.infrastructure.verification_report import LocalReportWriter
from outage_explorer.infrastructure.worker_runtime.configuration import (
    RuntimeEvidence,
    RuntimeProfile,
)
from outage_explorer.infrastructure.worker_runtime.unavailable import (
    UnavailableExecution,
    UnavailableInputs,
    UnavailableResults,
    UnavailableSequences,
)
from outage_explorer.settings import (
    AnalyticalWorkerSettings,
    ArtifactSettings,
    DatabaseSettings,
    ModelSettings,
    SourceSettings,
    artifact_settings,
    auth_settings,
    connector_settings,
    data_http_settings,
    database_settings,
    refresh_settings,
    s3_settings,
)


@dataclass(frozen=True)
class DataHttpResources:
    """Explicit analytical composition supplied only by a reviewed supervisor.

    Constructor/factory never starts resources. Supervisor invokes start after
    establishing process ownership; close is idempotent and process-bound.
    """

    inputs: PublishedInputs
    execution: IsolatedExecution
    results: QueryResults
    sequences: PreviewSequences
    encoding: TabularEncoding
    response_bytes: int
    start: Callable[[], None]
    close: Callable[[], None]
    evidence: str
    inspector: SqlInspector | None = None

    def __post_init__(self) -> None:
        if (
            not self.evidence
            or type(self.response_bytes) is not int
            or self.response_bytes <= 0
        ):
            raise ValueError("Explicit analytical bounds and evidence required")


def build_data_services(
    access: AccessService,
    store: PostgresqlPublicationStore,
    security: RandomSecurityMaterial,
    environment: Mapping[str, str],
    resources: DataHttpResources | None = None,
) -> DataServices:
    configuration = refresh_settings(environment)
    refresh = RefreshService(
        access,
        store,
        lambda: RefreshConfiguration(
            configuration.start_date,
            configuration.end_date,
            configuration.max_interval_days,
            configuration.source_interval_days,
            configuration.model_interval_days,
            configuration.candidate_seconds,
            configuration.persistence_seconds,
        ),
        security,
    )
    # With no reviewed runtime, reserve fails before preparation or source access.
    if resources is None:
        encoding: TabularEncoding = PreviewEncoding(
            EncodingBounds(1048576, 16, 10000, 100, 65536)
        )
        inputs: PublishedInputs = UnavailableInputs()
        execution: IsolatedExecution = UnavailableExecution()
        results: QueryResults = UnavailableResults()
        sequences: PreviewSequences = UnavailableSequences()
        response_bytes = 1048576
    else:
        encoding, inputs, execution, results, sequences, response_bytes = (
            resources.encoding,
            resources.inputs,
            resources.execution,
            resources.results,
            resources.sequences,
            resources.response_bytes,
        )
    return DataServices(
        CatalogService(access, store),
        PreviewService(
            access,
            store,
            inputs,
            execution,
            sequences,
            encoding,
            response_bytes=response_bytes,
        ),
        QueryService(
            access,
            resources.inspector
            if resources is not None and resources.inspector is not None
            else UnavailableSqlInspector(),
            store,
            inputs,
            execution,
            results,
        ),
        refresh,
        encoding,
    )


def build_http_app(*, data_resources: DataHttpResources | None = None) -> Flask:
    clock = SystemClock()
    try:
        settings = auth_settings(os.environ)
    except ValueError:
        raise AccessConfigurationError("Invalid authentication configuration") from None
    data = data_http_settings(os.environ)
    if data_resources is not None and not data.enabled:
        raise AccessConfigurationError(
            "Data HTTP resources require explicit enablement"
        )
    if settings is None:
        if data.enabled:
            raise AccessConfigurationError("Data HTTP requires authentication")
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
    data_closed = False

    def close() -> None:
        nonlocal closed, data_closed
        if os.getpid() != owner:
            return
        try:
            if data_resources is not None and not data_closed:
                data_resources.close()
                data_closed = True
        finally:
            if not closed:
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
            data_services=build_data_services(
                access,
                PostgresqlPublicationStore(pool),
                security,
                os.environ,
                data_resources,
            )
            if data.enabled
            else None,
        )
    except Exception:
        close()
        raise
    app.extensions["outage_access_close"] = close
    if data.enabled:
        app.extensions["outage_data_close"] = close
        if data_resources is not None:
            app.extensions["outage_data_start"] = data_resources.start
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


def build_refresh_worker(
    *,
    environment: Mapping[str, str] | None = None,
    transport: httpx.BaseTransport | None = None,
    client: Any = None,
) -> SupervisedRefreshProcess:
    """Explicit independent process composition; construction starts no jobs/I/O."""
    env = dict(os.environ if environment is None else environment)
    try:
        target = s3_settings(env)  # Fail before admitting any source work.
        database = database_settings(env)
        staging = env["OUTAGE_REFRESH_STAGING"]
        api_key = env["EIA_API_KEY"]
        if not staging or "\x00" in staging or not api_key:
            raise ValueError
    except (KeyError, ValueError):
        raise ConnectorConfigurationError(
            "Invalid refresh worker configuration"
        ) from None
    pool = _access_pool(database)
    store = PostgresqlPublicationStore(pool)
    lease = RenewableRefreshLease(store)

    @contextmanager
    def connector(run: RefreshRun, owner: RefreshOwner) -> Iterator[RefreshConnector]:
        config = run.configuration
        source_bounds = SourceBounds(
            **asdict(
                replace(
                    SourceSettings(),
                    interval_days=config.source_interval_days,
                    elapsed_seconds=config.candidate_seconds,
                )
            )
        )
        model_bounds = RefreshBounds(
            **asdict(
                replace(
                    ModelSettings(),
                    interval_days=config.model_interval_days,
                )
            )
        )
        artifacts = ArtifactBounds(**asdict(ArtifactSettings()))
        workers = BoundedConnectorWorkers(1, elapsed_seconds=config.candidate_seconds)

        active_workers = workers

        def check() -> None:
            lease.check()
            active_workers.check()

        local = LocalConnectorEvidence(
            LocalParquetStore(
                Path(staging) / run.id / "objects",
                artifacts,
                check,
            )
        )
        source_budget = SourceRunBudget(source_bounds, workers.cancelled)
        wire = transport
        sdk = client
        owned_wire, owned_sdk = wire is None, sdk is None
        try:
            if wire is None:
                wire = httpx.HTTPTransport(retries=0, trust_env=False)
            if sdk is None:
                sdk = boto3.Session(
                    profile_name=target.profile, region_name=target.region
                ).client(
                    "s3",
                    config=Config(
                        connect_timeout=10,
                        read_timeout=10,
                        retries={"mode": "standard", "total_max_attempts": 1},
                    ),
                )
            durable = S3ArtifactStore(
                sdk,
                target.bucket,
                target.prefix,
                artifacts,
                replace(TransferBounds(), elapsed_seconds=config.candidate_seconds),
            )
            reports = RefreshReports(store, owner)
            candidate = CreateConnectorCandidate(
                lambda request: EiaSource(
                    request, source_bounds, wire, api_key, budget=source_budget
                ),
                local,
                ParquetCandidateBuilder(local.store),
                reports,
                workers=workers,
            )

            def persist(
                reference: StoredObject, bounds: RefreshBounds
            ) -> DurableConnectorReceipt:
                nonlocal active_workers
                # Persistence has its own frozen deadline and full readback session.
                lease.check()
                remote = S3ArtifactStore(
                    sdk,
                    target.bucket,
                    target.prefix,
                    artifacts,
                    replace(
                        TransferBounds(), elapsed_seconds=config.persistence_seconds
                    ),
                )
                persistence_workers = BoundedConnectorWorkers(
                    1, elapsed_seconds=config.persistence_seconds
                )
                active_workers = persistence_workers
                return PersistConnectorArtifacts(
                    local, remote, workers=persistence_workers
                ).execute(reference, bounds)

            yield RefreshConnector(
                candidate,
                local,
                model_bounds,
                RecoverConnectorArtifacts(local, durable).execute,
                local.reopen,
                persist,
                durable.reference,
                SystemClock(),
            )
        finally:
            if owned_wire and wire is not None:
                wire.close()
            if owned_sdk and sdk is not None:
                sdk.close()

    execution = RefreshExecution(store, store, connector)
    worker = RefreshWorker(store, execution, lease, str(uuid4()))
    return SupervisedRefreshProcess(worker.tick, pool.close)


def build_query_result_lifecycle(
    root: Path,
    bounds: "ResultBounds",
    *,
    cleanup_interval_seconds: float,
) -> tuple["BoundedQueryResults", "QueryCleanup"]:
    """Construct inert process-owned resources; caller explicitly starts/closes."""
    store = BoundedQueryResults(root, SystemClock(), bounds)
    return store, QueryCleanup(store, interval_seconds=cleanup_interval_seconds)


def build_query_worker(
    *, inputs_root: Path | None = None, settings: AnalyticalWorkerSettings | None = None
) -> Callable[[bytes], bytes]:
    """Candidate container transport with explicit smoke-test limits only."""
    from outage_explorer.application.ports.execution import ExecutionBounds
    from outage_explorer.infrastructure.duckdb.previews import execute_preview
    from outage_explorer.infrastructure.duckdb.queries import execute_query
    from outage_explorer.infrastructure.sql_validation.inspection import (
        DuckdbSqlInspector,
    )
    from outage_explorer.infrastructure.worker_runtime.protocol import AnalyticalWorker
    from outage_explorer.settings import AnalyticalWorkerSettings

    settings = AnalyticalWorkerSettings() if settings is None else settings
    if settings != AnalyticalWorkerSettings():
        raise ValueError("Worker limits must match internal v1 image profile")
    bounds = ExecutionBounds(
        settings.preparation_seconds,
        settings.overall_seconds,
        settings.memory_bytes,
        settings.temporary_bytes,
        settings.output_bytes,
        settings.execution_seconds,
    )
    encoding = EncodingBounds(
        settings.max_cell_bytes,
        settings.max_depth,
        settings.max_nested_items,
        settings.max_columns,
        settings.max_schema_bytes,
    )
    worker = AnalyticalWorker(
        Path("/inputs") if inputs_root is None else inputs_root,
        lambda request: execute_preview(request, bounds),
        lambda request: execute_query(request, bounds, encoding),
        DuckdbSqlInspector(max_sql_bytes=65_536, max_nodes=10_000, max_depth=64),
        PreviewEncoding(encoding),
    )
    return worker.execute


def build_analytical_resources(
    profile: "RuntimeProfile",
    evidence: "RuntimeEvidence | None",
    *,
    inspector: SubprocessSqlInspector | None = None,
    local_acceptance: bool = False,
) -> DataHttpResources:
    """Build inert forwarding ports; only explicit start may own filesystem/S3."""
    from outage_explorer.infrastructure.local_cache.modeled import (
        CacheBounds,
        PublishedReadSessions,
        VerifiedModeledCache,
        reclaim_private_cache,
    )
    from outage_explorer.infrastructure.query_results.previews import (
        BoundedPreviewSequences,
        PreviewBounds,
    )
    from outage_explorer.infrastructure.worker_runtime.docker import (
        BoundedDockerControl,
        DockerRuntime,
    )
    from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
    from outage_explorer.infrastructure.worker_runtime.ownership import (
        OwnershipLedger,
        RecoveryOwner,
    )
    from outage_explorer.infrastructure.worker_runtime.supervisor import (
        AnalyticalResources,
        AnalyticalSupervisor,
    )

    control = BoundedDockerControl(profile.daemon_endpoint, profile.docker_executable)

    def reconcile(ledger: OwnershipLedger) -> None:
        DockerRuntime(profile, control, ledger).recover_owned()

    def construct(ledger: OwnershipLedger, key: bytes) -> AnalyticalResources:
        # Reviewed evidence remains required by supervisor.start. Real storage
        # prerequisites are checked here, before constructing cloud adapters.
        DockerRuntime(profile, control, ledger).validate_temporary_backend()
        s3 = s3_settings(os.environ)
        artifacts = ArtifactBounds(**asdict(ArtifactSettings()))
        transfer = TransferBounds(
            elapsed_seconds=profile.worker.preparation_seconds,
            timeout_seconds=min(10, profile.worker.preparation_seconds),
            wire_bytes=profile.input_bytes,
        )
        session = boto3.Session(profile_name=s3.profile, region_name=s3.region)
        wire = session.client(
            "s3",
            config=Config(
                connect_timeout=transfer.timeout_seconds,
                read_timeout=transfer.timeout_seconds,
                retries={"total_max_attempts": 1},
                max_pool_connections=1,
            ),
        )
        try:
            # Fresh bounded transfer session for each cache load, no lifetime budget.
            objects = PublishedReadSessions(
                lambda: S3ArtifactStore(wire, s3.bucket, s3.prefix, artifacts, transfer)
            )
            reclaim_private_cache(
                Path(profile.cache_root), file_limit=profile.input_files
            )
            cache = VerifiedModeledCache(
                Path(profile.cache_root),
                objects,
                artifacts,
                CacheBounds(
                    profile.cache_bytes,
                    profile.input_files,
                    30_000,
                    profile.worker.preparation_seconds,
                ),
            )
            runtime = DockerRuntime(profile, control, ledger)
            recovery = RecoveryOwner()
            launcher = VerifiedLauncher(
                profile.execution_bounds,
                runtime,
                evidence=evidence.profile_identity if evidence else None,
                recovery=recovery,
            )
            results = BoundedQueryResults(
                Path(profile.result_root),
                SystemClock(),
                ResultBounds(
                    profile.results_per_user,
                    profile.result_count,
                    profile.result_bytes,
                    131_072,
                ),
            )
            previews = BoundedPreviewSequences(
                SystemClock(),
                PreviewBounds(
                    profile.results_per_user,
                    profile.result_count,
                    profile.result_bytes,
                    4096,
                ),
                key,
            )

            def close_inputs() -> None:
                cache.close()
                wire.close()

            return AnalyticalResources(
                cache,
                launcher,
                results,
                previews,
                recovery,
                runtime.terminate_and_reap,
                runtime.cancel.set,
                close_inputs,
            )
        except BaseException:
            wire.close()
            raise

    supervisor = AnalyticalSupervisor(
        profile, evidence, construct, reconcile, local_acceptance=local_acceptance
    )

    def start() -> None:
        # Reject an unreviewed runtime before acquiring parser ownership, too.
        if evidence is None:
            raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")
        evidence.require_ready(profile, started=True, local_acceptance=local_acceptance)
        try:
            if inspector is not None:
                inspector.start()
            supervisor.start()
        except BaseException:
            if inspector is not None:
                inspector.close()
            raise

    def close() -> None:
        try:
            if inspector is not None:
                inspector.close()
        finally:
            supervisor.close()

    return DataHttpResources(
        supervisor.inputs,
        supervisor.execution,
        supervisor.results,
        supervisor.sequences,
        PreviewEncoding(profile.encoding_bounds),
        profile.worker.output_bytes,
        start,
        close,
        profile.identity,
        inspector,
    )


def execute_analytical_http(
    config_path: str, host: str, port: int, inspection_path: str | None = None
) -> int:
    """Explicit local lifecycle; no reloader or extra serving process is supported."""
    from outage_explorer.infrastructure.worker_runtime.configuration import (
        read_runtime_config,
    )

    if (
        host not in {"127.0.0.1", "localhost"}
        or type(port) is not int
        or not 1 <= port <= 65535
        or any(
            os.environ.get(name) not in (None, "", "0", "false")
            for name in ("WERKZEUG_RUN_MAIN", "FLASK_DEBUG")
        )
        or os.environ.get("WEB_CONCURRENCY", "1") != "1"
    ):
        raise ValueError("Unsupported analytical serving mode")
    profile, evidence = read_runtime_config(Path(config_path))
    inspector = None
    if inspection_path is not None:
        from outage_explorer.infrastructure.sql_validation.configuration import (
            read_inspection_config,
        )

        parser_profile, parser_review = read_inspection_config(Path(inspection_path))
        if parser_review is None:
            raise RuntimeUnavailableError("Reviewed SQL inspection unavailable")
        parser_review.require_ready(parser_profile)
        inspector = parser_profile.build()
    if evidence is None:
        raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")
    evidence.require_ready(profile, started=True, local_acceptance=True)
    resources = build_analytical_resources(
        profile, evidence, inspector=inspector, local_acceptance=True
    )
    app: Flask | None = None
    try:
        app = build_http_app(data_resources=resources)
        resources.start()
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
    finally:
        try:
            if app is not None:
                app.extensions["outage_data_close"]()
        finally:
            resources.close()
    return 0
