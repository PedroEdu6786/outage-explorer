"""Fail-closed launcher seam. No subprocess is advertised as OS isolation."""

from threading import Lock
from time import monotonic
from typing import Protocol

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.execution import (
    ExecutionBounds,
    PreviewRead,
    PreviewRows,
    QueryRead,
    RecoveryLease,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.infrastructure.worker_runtime.ownership import RecoveryOwner


class ReviewedRuntime(Protocol):
    """Adapter contract; activation requires reviewed denial/limits/reaping evidence.

    Run must enforce the supplied hard limits and immutable approved files.
    Termination must cover the complete worker tree; return only after reaping.
    """

    def preview(
        self, request: PreviewRead, bounds: ExecutionBounds, deadline: float
    ) -> PreviewRows: ...
    def query(
        self, request: QueryRead, bounds: ExecutionBounds, deadline: float
    ) -> QueryOutput: ...
    def terminate_and_reap(self) -> None: ...


class VerifiedLauncher:
    def __init__(
        self,
        bounds: ExecutionBounds,
        runtime: ReviewedRuntime | None = None,
        *,
        evidence: str | None = None,
        recovery: RecoveryOwner | None = None,
    ) -> None:
        if runtime is not None and not evidence:
            raise ValueError("Reviewed runtime evidence reference required")
        self._bounds, self._runtime = bounds, runtime
        self._slot = Lock()
        self._guard = Lock()
        self._accepting = True
        self.recovery = recovery if recovery is not None else RecoveryOwner()

    def reserve(self) -> "_Reservation":
        with self._guard:
            if self._runtime is None or not self._accepting:
                raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")
            if not self._slot.acquire(blocking=False):
                raise AnalyticalBusyError("Analytical execution busy")
            return _Reservation(self._slot, self._runtime, self._bounds, self.recovery)

    def stop(self) -> None:
        with self._guard:
            self._accepting = False

    @property
    def active(self) -> bool:
        return self._slot.locked()


class _Reservation:
    def __init__(
        self,
        slot: Lock,
        runtime: ReviewedRuntime,
        bounds: ExecutionBounds,
        recovery: RecoveryOwner,
    ) -> None:
        self._slot, self._runtime, self._bounds = slot, runtime, bounds
        self._recovery = recovery
        self._handed_off = False
        self._started = monotonic()
        self._closed = False

    def handoff(self, leases: tuple[RecoveryLease, ...]) -> None:
        if not self._handed_off:
            self._recovery.retain(self.close, leases)
            self._handed_off = True

    def check_preparation(self) -> None:
        if self._closed or monotonic() - self._started >= min(
            self._bounds.preparation_seconds, self._bounds.overall_seconds
        ):
            raise AnalyticalResourceError("Analytical preparation deadline exceeded")

    def preview(self, request: PreviewRead) -> PreviewRows:
        self.check_preparation()
        deadline = min(
            self._started + self._bounds.overall_seconds,
            monotonic() + self._bounds.execution_seconds,
        )
        result = self._runtime.preview(request, self._bounds, deadline)
        if monotonic() >= deadline:
            raise AnalyticalResourceError("Analytical execution deadline exceeded")
        return result

    def query(self, request: QueryRead) -> QueryOutput:
        self.check_preparation()
        deadline = min(
            self._started + self._bounds.overall_seconds,
            monotonic() + self._bounds.execution_seconds,
        )
        result = self._runtime.query(request, self._bounds, deadline)
        if monotonic() >= deadline:
            raise AnalyticalTimeoutError("Analytical execution deadline exceeded")
        return result

    def close(self) -> None:
        if not self._closed:
            # A failed reap deliberately retains the slot: uncertain worker liveness.
            self._runtime.terminate_and_reap()
            self._closed = True
            self._slot.release()
