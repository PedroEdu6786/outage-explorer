"""Explicit process polling and independent database-time lease renewal."""

import signal
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from threading import Event, Thread
from types import FrameType

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
    """Poll for refresh work until shutdown, with explicit resource cleanup."""

    def __init__(
        self,
        tick: Callable[[], object],
        close: Callable[[], None],
        poll_seconds: float = 1,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("Invalid poll interval")
        self.tick = tick
        self._close_resources = close
        self.poll_seconds = poll_seconds
        self.stopped = Event()
        self.closed = False

    def run(self) -> int:
        previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        try:
            self._poll_for_refresh_work()
        except KeyboardInterrupt:
            self.stopped.set()
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm_handler)
        return 0

    def _handle_shutdown_signal(
        self, signal_number: int, frame: FrameType | None
    ) -> None:
        self.stopped.set()

    def _poll_for_refresh_work(self) -> None:
        while not self.stopped.is_set():
            try:
                self.tick()
            except (AccessStoreError, StaleRefreshOwnerError):
                # The next tick reconciles unfinished work before claiming a run.
                pass
            # Waiting on the event lets a shutdown request end the pause early.
            self.stopped.wait(self.poll_seconds)

    def close(self) -> None:
        self.stopped.set()
        if self.closed:
            return

        self.closed = True
        self._close_resources()
