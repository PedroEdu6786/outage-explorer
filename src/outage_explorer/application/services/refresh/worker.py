"""Recover, claim and supervise one refresh run per worker tick."""

from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.application.ports.refresh_execution import RefreshLease
from outage_explorer.application.services.refresh.execution import RefreshExecution
from outage_explorer.application.services.refresh.recovery import RefreshRecovery
from outage_explorer.domain.publication import RefreshOwner, RefreshRun


class RefreshWorker:
    def __init__(
        self,
        store: RefreshStore,
        execution: RefreshExecution,
        lease: RefreshLease,
        identity: str,
        lease_seconds: int = 60,
    ) -> None:
        self.store = store
        self.execution = execution
        self.lease = lease
        self.identity = identity
        self.lease_seconds = lease_seconds

    def tick(self) -> RefreshRun | None:
        """Recover unfinished work, then claim and execute at most one queued run."""
        self._recover_unfinished_run()

        claimed_owner = self.store.claim(self.identity, self.lease_seconds)
        if claimed_owner is None:
            return None

        return self._execute_claimed_run(claimed_owner)

    def _recover_unfinished_run(self) -> None:
        latest_run = self.store.latest()
        if latest_run is None:
            return
        if latest_run.status.terminal:
            return

        RefreshRecovery(self.store).execute(latest_run.id)

    def _execute_claimed_run(self, owner: RefreshOwner) -> RefreshRun:
        """Keep renewing ownership until execution returns or raises an error."""
        with self.lease(owner):
            return self.execution.execute(owner)
