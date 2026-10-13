"""Explicit process polling and independent database-time lease renewal."""

import signal
from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Event, Thread
from types import FrameType

from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.refresh import RefreshStore
from outage_explorer.domain.publication import RefreshOwner


class RenewableRefreshLease:
    """Keep refresh ownership alive while work runs inside the context."""

    def __init__(
        self, store: RefreshStore, seconds: int = 60, renew_seconds: float = 10
    ) -> None:
        if not 0 < renew_seconds < seconds:
            raise ValueError("Invalid renewal interval")
        self.store = store
        self.seconds = seconds
        self.renew_seconds = renew_seconds
        self.failure: Exception | None = None

    def check(self) -> None:
        """Raise any heartbeat failure in the thread performing the refresh."""
        if self.failure is not None:
            raise self.failure

    @contextmanager
    def __call__(self, owner: RefreshOwner) -> Generator[None]:
        """Start lease renewal on entry and stop it when refresh work exits."""
        stop_renewal = Event()
        self.failure = None

        # Ownership was committed before this thread and any source retrieval.
        renewal_thread = Thread(
            target=self._renew_until_stopped,
            args=(owner, stop_renewal),
            name="refresh-lease",
            daemon=False,
        )
        renewal_thread.start()
        try:
            yield
        finally:
            stop_renewal.set()
            renewal_thread.join()

    def _renew_until_stopped(self, owner: RefreshOwner, stop_renewal: Event) -> None:
        while True:
            # Wait between heartbeats, waking immediately when work finishes.
            if stop_renewal.wait(self.renew_seconds):
                return

            try:
                self.store.heartbeat(owner, self.seconds)
            except Exception as error:
                # Save the failure for check(); exceptions cannot cross threads.
                self.failure = error
                return


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
