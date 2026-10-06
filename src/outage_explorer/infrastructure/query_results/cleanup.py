"""Explicit process lifecycle; no import, factory or request owns cleanup threads."""

import logging
from collections.abc import Callable
from threading import Event, Thread

from outage_explorer.infrastructure.query_results.store import BoundedQueryResults

_LOG = logging.getLogger(__name__)


class QueryCleanup:
    def __init__(
        self,
        store: BoundedQueryResults,
        *,
        interval_seconds: float,
        before_cleanup: Callable[[], None] = lambda: None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("Positive cleanup interval required")
        self._store, self._interval = store, interval_seconds
        self._before_cleanup = before_cleanup
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self, *, serving_processes: int = 1) -> None:
        if self._thread is not None:
            return
        self._store.start(serving_processes=serving_processes)
        self.sweep()
        self._thread = Thread(
            target=self._run, name="query-result-cleanup", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.sweep()
            except Exception:
                # Diagnostics never contain private file paths or output cells.
                _LOG.error("Query result cleanup failed")

    def sweep(self) -> None:
        self._before_cleanup()
        self._store.cleanup()

    def stop(self, *, timeout: float | None = None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                raise RuntimeError("Analytical cleanup still active")
            self._thread = None

    def close(self) -> None:
        self.stop()
        self._store.close()
