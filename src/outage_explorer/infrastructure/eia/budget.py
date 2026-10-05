"""One deadline and atomic retrieval counters for all endpoints in a run."""

import time
from threading import Event, Lock

from outage_explorer.application.ports.source import SourceBounds, SourceLimitError


class SourceRunBudget:
    def __init__(self, bounds: SourceBounds, cancelled: Event) -> None:
        self.bounds, self.cancelled = bounds, cancelled
        self.deadline = time.monotonic() + bounds.elapsed_seconds
        self.lock = Lock()
        self.counts: dict[str, int] = {}

    def remaining(self) -> float:
        remaining = self.deadline - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise SourceLimitError("Aggregate retrieval cancelled or expired")
        return remaining

    def charge(self, name: str, size: int) -> None:
        with self.lock:
            self.remaining()
            count = self.counts.get(name, 0) + size
            if count > getattr(self.bounds, name):
                self.cancelled.set()
                raise SourceLimitError("Aggregate source resource bound exceeded")
            self.counts[name] = count
