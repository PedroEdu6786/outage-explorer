"""Per-run refresh pipeline composition, invoked by the process bootstrap."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from threading import Event
from typing import Any

import boto3  # type: ignore[import-untyped]
import httpx
from botocore.config import Config  # type: ignore[import-untyped]

from outage_explorer.application.errors import ConnectorConfigurationError
from outage_explorer.application.ports.artifacts import ArtifactBounds, TransferBounds
from outage_explorer.application.ports.candidates import CandidateResult
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.ports.refresh_execution import (
    RefreshPipeline,
    RefreshPipelineFactory,
)
from outage_explorer.application.ports.source import SourceBounds
from outage_explorer.application.services.connector import CreateResourceCandidate
from outage_explorer.application.services.refresh_baseline import RestoreRefreshBaseline
from outage_explorer.application.services.refresh_candidate import (
    PrepareRefreshCandidate,
)
from outage_explorer.application.services.refresh_execution import RefreshReports
from outage_explorer.application.services.refresh_publication import (
    PrepareRefreshPublication,
)
from outage_explorer.application.services.resource_artifacts import (
    PersistResourceArtifacts,
    RecoverResourceArtifacts,
)
from outage_explorer.configuration.connector import (
    ArtifactSettings,
    ModelSettings,
    ResourceWorkerSettings,
    SourceSettings,
    resource_worker_settings,
)
from outage_explorer.configuration.s3 import S3Settings
from outage_explorer.domain.publication import (
    RefreshConfiguration,
    RefreshOwner,
    RefreshRun,
)
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.clock import SystemClock
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers
from outage_explorer.infrastructure.eia.budget import SourceRunBudget
from outage_explorer.infrastructure.eia.source import EiaSource
from outage_explorer.infrastructure.parquet.candidates import ParquetResourceBuilder
from outage_explorer.infrastructure.parquet.connector import LocalConnectorEvidence
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlResourcePublicationStore,
)
from outage_explorer.infrastructure.refresh_worker import RenewableRefreshLease
from outage_explorer.infrastructure.s3.resources import S3ResourceStore


@dataclass(frozen=True)
class _RefreshRunLimits:
    source: SourceBounds
    model: RefreshBounds
    artifacts: ArtifactBounds
    workers: ResourceWorkerSettings


def _refresh_run_limits(config: RefreshConfiguration) -> _RefreshRunLimits:
    source = SourceBounds(
        **asdict(
            replace(
                SourceSettings(),
                interval_days=config.source_interval_days,
                elapsed_seconds=config.candidate_seconds,
            )
        )
    )
    model = RefreshBounds(
        **asdict(
            replace(
                ModelSettings(),
                interval_days=config.model_interval_days,
            )
        )
    )
    artifacts = ArtifactBounds(**asdict(ArtifactSettings()))
    workers = resource_worker_settings({}, s3=config.s3_workers)
    if (
        workers.s3_workers * (2 * artifacts.file_bytes + artifacts.row_group_bytes)
        > workers.memory_bytes
        or 2 * artifacts.total_bytes + workers.s3_workers * artifacts.file_bytes
        > workers.temporary_bytes
    ):
        raise ConnectorConfigurationError("Invalid refresh worker limits")
    return _RefreshRunLimits(source, model, artifacts, workers)


class _PhaseCancellation(Event):
    """Route cancellation to whichever worker phase currently owns the run."""

    def __init__(self, run: _RunPipelineComposition) -> None:
        super().__init__()
        self._run = run

    def is_set(self) -> bool:
        self._run.lease.check()
        return self._run.active_workers.cancelled.is_set()

    def set(self) -> None:
        self._run.active_workers.cancelled.set()


class _RunPipelineComposition:
    """Own one run's local files, provider clients, and phase-specific workers."""

    def __init__(
        self,
        run: RefreshRun,
        owner: RefreshOwner,
        store: PostgresqlResourcePublicationStore,
        lease: RenewableRefreshLease,
        target: S3Settings,
        staging: str,
        api_key: str,
        transport: httpx.BaseTransport | None,
        client: Any,
    ) -> None:
        self.config = run.configuration
        self.limits = _refresh_run_limits(self.config)
        self.owner = owner
        self.store = store
        self.lease = lease
        self.target = target
        self.api_key = api_key
        self.run_root = Path(staging) / run.id
        self.candidate_workers = BoundedConnectorWorkers(
            1, elapsed_seconds=self.config.candidate_seconds
        )
        self.active_workers = self.candidate_workers
        self.cancellation = _PhaseCancellation(self)
        self.wire = transport
        self.sdk = client
        self.owned_wire = transport is None
        self.owned_sdk = client is None

    def check(self) -> None:
        self.lease.check()
        self.active_workers.check()

    def _local_evidence(self) -> LocalConnectorEvidence:
        self.run_root.mkdir(parents=True, exist_ok=False)
        return LocalConnectorEvidence(
            LocalParquetStore(
                self.run_root / "objects", self.limits.artifacts, self.check
            ),
            self.candidate_workers,
        )

    def _open_clients(self) -> None:
        if self.wire is None:
            self.wire = httpx.HTTPTransport(retries=0, trust_env=False)
        if self.sdk is None:
            self.sdk = boto3.Session(
                profile_name=self.target.profile, region_name=self.target.region
            ).client(
                "s3",
                config=Config(
                    connect_timeout=10,
                    read_timeout=10,
                    retries={"mode": "standard", "total_max_attempts": 1},
                    max_pool_connections=self.limits.workers.s3_workers,
                ),
            )

    def _resource_store(self, elapsed_seconds: int) -> S3ResourceStore:
        return S3ResourceStore(
            self.sdk,
            self.target.bucket,
            self.target.prefix,
            self.limits.artifacts,
            replace(
                TransferBounds(),
                elapsed_seconds=elapsed_seconds,
                temporary_bytes=self.limits.workers.temporary_bytes,
            ),
            cancelled=self.cancellation,
        )

    def _candidate(
        self, local: LocalConnectorEvidence, source_budget: SourceRunBudget
    ) -> CreateResourceCandidate:
        wire = self.wire
        assert wire is not None
        return CreateResourceCandidate(
            lambda request: EiaSource(
                request,
                self.limits.source,
                wire,
                self.api_key,
                budget=source_budget,
            ),
            local,
            ParquetResourceBuilder(local.store),
            RefreshReports(self.store, self.owner),
            workers=self.candidate_workers,
        )

    def _persist(
        self,
        local: LocalConnectorEvidence,
        verified: CandidateResult,
        bounds: RefreshBounds,
    ) -> DurableResourceReceipt:
        self.lease.check()
        workers = BoundedConnectorWorkers(
            self.limits.workers.s3_workers,
            elapsed_seconds=self.config.persistence_seconds,
        )
        self.active_workers = workers
        local.workers = workers
        remote = self._resource_store(self.config.persistence_seconds)
        return PersistResourceArtifacts(local, remote, workers=workers).execute(
            verified, bounds
        )

    def _pipeline(
        self,
        local: LocalConnectorEvidence,
        durable: S3ResourceStore,
        source_budget: SourceRunBudget,
    ) -> RefreshPipeline:
        model_bounds = self.limits.model
        return RefreshPipeline(
            baseline=RestoreRefreshBaseline(
                self.store,
                self.store,
                RecoverResourceArtifacts(local, durable).execute,
                model_bounds,
            ),
            candidate=PrepareRefreshCandidate(
                self._candidate(local, source_budget),
                local.verify_candidate,
                model_bounds,
            ),
            publication=PrepareRefreshPublication(
                durable.addresses,
                lambda verified, bounds: self._persist(local, verified, bounds),
                model_bounds,
                SystemClock(),
            ),
        )

    def _close(self) -> None:
        try:
            shutil.rmtree(self.run_root)
        finally:
            try:
                if self.owned_wire and self.wire is not None:
                    self.wire.close()
            finally:
                if self.owned_sdk and self.sdk is not None:
                    self.sdk.close()

    @contextmanager
    def open(self) -> Iterator[RefreshPipeline]:
        local = self._local_evidence()
        source_budget = SourceRunBudget(self.limits.source, self.cancellation)
        try:
            self._open_clients()
            durable = self._resource_store(self.config.candidate_seconds)
            yield self._pipeline(local, durable, source_budget)
        finally:
            self._close()


def refresh_pipeline_factory(
    store: PostgresqlResourcePublicationStore,
    lease: RenewableRefreshLease,
    target: S3Settings,
    staging: str,
    api_key: str,
    transport: httpx.BaseTransport | None,
    client: Any,
) -> RefreshPipelineFactory:
    """Bind process dependencies; create run resources only when called."""

    @contextmanager
    def pipeline(run: RefreshRun, owner: RefreshOwner) -> Iterator[RefreshPipeline]:
        composition = _RunPipelineComposition(
            run, owner, store, lease, target, staging, api_key, transport, client
        )
        with composition.open() as assembled:
            yield assembled

    return pipeline
