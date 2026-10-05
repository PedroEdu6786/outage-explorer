"""Reconcile durable publication before releasing lost work; never rerun sources."""

from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.domain.publication import RefreshRun


class RefreshRecovery:
    def __init__(self, store: RefreshStore) -> None:
        self.store = store

    def execute(self, run_id: str) -> RefreshRun:
        # The store serializes on the publication coordination row, checks history,
        # and fences expired epochs. Database unavailability propagates unchanged.
        return self.store.recover(run_id)
