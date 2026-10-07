"""Explicit single-process analytical ownership; construction performs no I/O."""

import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import RLock
from uuid import uuid4

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.application.ports.analytical_inputs import (
    PinnedInputs,
    PublishedResourceInputs,
)
from outage_explorer.application.ports.execution import ExecutionReservation
from outage_explorer.application.ports.preview_sequences import (
    PreviewPosition,
    PreviewSequence,
)
from outage_explorer.application.ports.query_results import (
    ResultReader,
    ResultReservation,
)
from outage_explorer.domain.datasets import Dataset
from outage_explorer.domain.publication import ResourcePublishedGeneration
from outage_explorer.infrastructure.query_results.cleanup import QueryCleanup
from outage_explorer.infrastructure.query_results.previews import (
    BoundedPreviewSequences,
)
from outage_explorer.infrastructure.query_results.store import BoundedQueryResults
from outage_explorer.infrastructure.worker_runtime.configuration import (
    RuntimeEvidence,
    RuntimeProfile,
)
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from outage_explorer.infrastructure.worker_runtime.ownership import (
    OwnershipLedger,
    RecoveryOwner,
)


@dataclass(frozen=True)
class AnalyticalResources:
    inputs: PublishedResourceInputs
    execution: VerifiedLauncher
    results: BoundedQueryResults
    sequences: BoundedPreviewSequences
    recovery: RecoveryOwner
    terminate: Callable[[], None]
    cancel: Callable[[], None]
    close_inputs: Callable[[], None]


class AnalyticalSupervisor:
    def __init__(
        self,
        profile: RuntimeProfile,
        evidence: RuntimeEvidence | None,
        construct: Callable[[OwnershipLedger, bytes], AnalyticalResources],
        reconcile: Callable[[OwnershipLedger], None],
        *,
        local_acceptance: bool = False,
    ) -> None:
        self.profile, self.evidence = profile, evidence
        self._construct, self._reconcile = construct, reconcile
        self._local_acceptance = local_acceptance
        self._pid = os.getpid()
        self._ledger = OwnershipLedger(Path(profile.staging_root), uuid4().hex)
        self._resources: AnalyticalResources | None = None
        self._started = False
        self._closed = False
        self._lock = RLock()
        self._cleanup: QueryCleanup | None = None
        self.inputs = ForwardInputs(self)
        self.execution = ForwardExecution(self)
        self.results = ForwardResults(self)
        self.sequences = ForwardSequences(self)

    def _check_process(self) -> None:
        if os.getpid() != self._pid:
            raise RuntimeUnavailableError("Analytical process ownership changed")

    def ready(self) -> AnalyticalResources:
        with self._lock:
            self._check_process()
            if not self._started or self._resources is None:
                raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")
            return self._resources

    def start(self, *, serving_processes: int = 1, reloader: bool = False) -> None:
        with self._lock:
            self._check_process()
            if serving_processes != 1 or reloader or self._closed:
                raise RuntimeUnavailableError("Unsupported analytical serving mode")
            if self._started:
                return
            if self.evidence is None:
                raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")
            self.evidence.require_ready(
                self.profile, started=True, local_acceptance=self._local_acceptance
            )
            try:
                self._ledger.open()
                self._reconcile(self._ledger)
                self._resources = self._construct(self._ledger, secrets.token_bytes(32))
                self._cleanup = QueryCleanup(
                    self._resources.results,
                    interval_seconds=self.profile.cleanup_interval_seconds,
                    before_cleanup=self._maintenance,
                )
                self._cleanup.start()
                self._started = True
            except BaseException:
                self.close()
                raise

    def sweep(self) -> None:
        """Recover workers before expired pins/results can be reclaimed."""
        self._check_process()
        resources = self._resources
        if resources is not None:
            self._maintenance()
            resources.results.cleanup()

    def _maintenance(self) -> None:
        self._check_process()
        resources = self._resources
        if resources is not None:
            resources.recovery.reconcile()
            resources.sequences.cleanup()

    def close(self) -> None:
        self._check_process()
        with self._lock:
            self._started = False
            self._closed = True
            resources = self._resources
            if resources is not None:
                resources.execution.stop()
                resources.cancel()
        if self._cleanup is not None:
            self._cleanup.stop(timeout=self.profile.termination_seconds + 1)
        resources = self._resources
        if resources is not None:
            resources.recovery.reconcile()
            if resources.recovery.pending or resources.execution.active:
                raise RuntimeUnavailableError("Analytical recovery unresolved")
            resources.terminate()
            resources.sequences.close()
            if resources.sequences.active_leases:
                raise RuntimeUnavailableError("Active analytical preview readers")
            resources.results.close()
            resources.close_inputs()
            self._resources = None
        self._ledger.close()


class ForwardInputs:
    def __init__(self, supervisor: AnalyticalSupervisor) -> None:
        self._supervisor = supervisor

    def prepare(
        self, generation: ResourcePublishedGeneration, dataset: Dataset
    ) -> PinnedInputs:
        return self._supervisor.ready().inputs.prepare(generation, dataset)


class ForwardExecution:
    def __init__(self, supervisor: AnalyticalSupervisor) -> None:
        self._supervisor = supervisor

    def reserve(self) -> ExecutionReservation:
        return self._supervisor.ready().execution.reserve()


class ForwardResults:
    def __init__(self, supervisor: AnalyticalSupervisor) -> None:
        self._supervisor = supervisor

    def reserve(self, owner: str) -> ResultReservation:
        return self._supervisor.ready().results.reserve(owner)

    def acquire(self, query_id: str, owner: str) -> ResultReader:
        return self._supervisor.ready().results.acquire(query_id, owner)


class ForwardSequences:
    def __init__(self, supervisor: AnalyticalSupervisor) -> None:
        self._supervisor = supervisor

    def create(
        self,
        user_id: str,
        dataset: Dataset,
        generation: ResourcePublishedGeneration,
        start: date | None,
        end: date | None,
        size: int,
        inputs: PinnedInputs,
    ) -> PreviewSequence:
        return self._supervisor.ready().sequences.create(
            user_id, dataset, generation, start, end, size, inputs
        )

    def cursor(self, sequence: PreviewSequence, after: tuple[str, ...] | None) -> str:
        return self._supervisor.ready().sequences.cursor(sequence, after)

    def acquire(self, cursor: str, user_id: str, dataset: Dataset) -> PreviewPosition:
        return self._supervisor.ready().sequences.acquire(cursor, user_id, dataset)

    def release(self, sequence: PreviewSequence) -> None:
        self._supervisor._check_process()
        # Active leases must be releasable after admission stops.
        resources = self._supervisor._resources
        if resources is not None:
            resources.sequences.release(sequence)

    def discard(self, sequence: PreviewSequence) -> None:
        self._supervisor._check_process()
        resources = self._supervisor._resources
        if resources is not None:
            resources.sequences.discard(sequence)

    def cleanup(self) -> None:
        self._supervisor.sweep()
