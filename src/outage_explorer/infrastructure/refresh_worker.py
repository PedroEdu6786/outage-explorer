"""Explicit process polling and independent database-time lease renewal."""

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Thread

from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.domain.publication import RefreshOwner


class RenewableRefreshLease:
    def __init__(
        self, store: RefreshStore, seconds: int = 60, renew_seconds: float = 10
    ) -> None:
        if not 0 < renew_seconds < seconds:
            raise ValueError("Invalid renewal interval")
        self.store, self.seconds, self.renew_seconds = store, seconds, renew_seconds
        self.failure: Exception | None = None

    def check(self) -> None:
        if self.failure is not None:
            raise self.failure

    @contextmanager
    def __call__(self, owner: RefreshOwner) -> Iterator[None]:
        stopped = Event()
        self.failure = None

        def renew() -> None:
            while not stopped.wait(self.renew_seconds):
                try:
                    self.store.heartbeat(owner, self.seconds)
                except Exception as error:
                    self.failure = error
                    return

        # Ownership was committed before this thread and any source retrieval.
        thread = Thread(target=renew, name="refresh-lease", daemon=False)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join()


class SupervisedRefreshProcess:
    def __init__(
        self,
        tick: Callable[[], object],
        close: Callable[[], None],
        poll_seconds: float = 1,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("Invalid poll interval")
        self.tick, self._close, self.poll_seconds = tick, close, poll_seconds
        self.stopped = Event()
        self.closed = False

    def run(self) -> int:
        previous = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, lambda *_: self.stopped.set())
        try:
            while not self.stopped.is_set():
                try:
                    self.tick()
                except (AccessStoreError, StaleRefreshOwnerError):
                    pass  # Remain occupied until durable reconciliation succeeds.
                self.stopped.wait(self.poll_seconds)
        except KeyboardInterrupt:
            self.stopped.set()
        finally:
            signal.signal(signal.SIGTERM, previous)
        return 0

    def close(self) -> None:
        self.stopped.set()
        if not self.closed:
            self.closed = True
            self._close()
