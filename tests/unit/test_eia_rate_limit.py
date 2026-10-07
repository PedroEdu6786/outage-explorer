"""Pacing has one shared schedule, no catch-up burst, and bounded waiting."""

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock

import pytest

from outage_explorer.application.ports.source import SourceLimitError
from outage_explorer.infrastructure.eia.rate_limit import SourceRateLimiter
from tests.integration.test_eia_source import Clock


def test_spacing_has_no_credit_after_idle_or_delayed_wakeup():
    clock = Clock()
    limiter = SourceRateLimiter(1000, clock)
    arrivals = []
    for _ in range(3):
        limiter.acquire(lambda: 100, clock.sleep)
        arrivals.append(clock())
    clock.value = 10
    limiter.acquire(lambda: 100, clock.sleep)
    arrivals.append(clock())

    def late_wakeup(_):
        clock.value += 5

    limiter.acquire(lambda: 100, late_wakeup)
    arrivals.append(clock())
    limiter.acquire(lambda: 100, clock.sleep)
    arrivals.append(clock())
    assert arrivals == pytest.approx([0, 1, 2, 10, 15, 16])


def test_shorter_cooldown_does_not_shorten_existing_cooldown():
    clock = Clock()
    limiter = SourceRateLimiter(1000, clock)
    limiter.defer(10)
    limiter.defer(2)
    limiter.acquire(lambda: 100, clock.sleep)
    assert clock() == pytest.approx(10)
    limiter.acquire(lambda: 100, clock.sleep)
    assert clock() == pytest.approx(11)


def test_cooldown_added_while_waiting_is_rechecked():
    clock = Clock()
    limiter = SourceRateLimiter(1000, clock)
    limiter.acquire(lambda: 100, clock.sleep)

    def extend_once(delay):
        clock.sleep(delay)
        if len(clock.sleeps) == 1:
            limiter.defer(10)

    limiter.acquire(lambda: 100, extend_once)
    assert clock() == pytest.approx(10.1)


def test_wait_cancels_before_next_admission():
    clock = Clock()
    limiter = SourceRateLimiter(1000, clock)
    limiter.defer(120)
    cancelled = Event()

    def remaining():
        if cancelled.is_set():
            raise SourceLimitError("cancelled")
        return 1800

    def cancel(delay):
        clock.sleep(delay)
        cancelled.set()

    with pytest.raises(SourceLimitError, match="cancelled"):
        limiter.acquire(remaining, cancel)
    assert clock() <= 0.1


def test_wait_rejects_deadline_and_oversleep():
    clock = Clock()
    limiter = SourceRateLimiter(1000, clock)
    limiter.defer(10)
    with pytest.raises(SourceLimitError, match="deadline"):
        limiter.acquire(lambda: 10, clock.sleep)
    assert clock.sleeps == []

    def remaining():
        if clock() >= 11:
            raise SourceLimitError("expired")
        return 11 - clock()

    def oversleep(_):
        clock.value = 12

    with pytest.raises(SourceLimitError, match="expired"):
        limiter.acquire(remaining, oversleep)


def test_parallel_callers_share_spacing_without_serializing_responses():
    limiter = SourceRateLimiter(20)
    start = Barrier(3)
    in_flight = Barrier(3, timeout=2)
    lock = Lock()
    arrivals = []

    def request():
        start.wait(timeout=2)
        limiter.acquire(lambda: 10, time.sleep)
        with lock:
            arrivals.append(time.monotonic())
        # Every request can remain in flight while later ones are admitted.
        in_flight.wait()

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(request) for _ in range(3)]
        for future in futures:
            future.result(timeout=3)
    assert len(arrivals) == 3
    assert all(b - a >= 0.019 for a, b in zip(arrivals, arrivals[1:], strict=False))
