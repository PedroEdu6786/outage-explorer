"""Thread-safe request spacing and cooldown shared by one retrieval run."""

import time
from collections.abc import Callable
from threading import Lock

from outage_explorer.application.ports.source import SourceLimitError

_POLL_SECONDS = 0.1


class SourceRateLimiter:
    def __init__(
        self,
        interval_milliseconds: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = interval_milliseconds / 1_000
        self._clock = monotonic
        self._lock = Lock()
        self._next = 0.0

    def defer(self, delay: float) -> None:
        with self._lock:
            self._next = max(self._next, self._clock() + delay)

    def acquire(
        self, remaining: Callable[[], float], sleep: Callable[[float], None]
    ) -> None:
        while True:
            with self._lock:
                available = remaining()
                now = self._clock()
                delay = self._next - now
                if delay <= 0:
                    # Start from actual admission, never bank unused burst credit.
                    self._next = now + self._interval
                    return
                if delay >= available:
                    raise SourceLimitError(
                        "Rate limit delay exceeds retrieval deadline"
                    )
            sleep(min(delay, _POLL_SECONDS))


def wait_for_retry(
    delay: float,
    monotonic: Callable[[], float],
    remaining: Callable[[], float],
    sleep: Callable[[float], None],
) -> None:
    until = monotonic() + delay
    while True:
        available = remaining()
        delay = until - monotonic()
        if delay <= 0:
            return
        if delay >= available:
            raise SourceLimitError("Retry delay exceeds retrieval deadline")
        sleep(min(delay, _POLL_SECONDS))
