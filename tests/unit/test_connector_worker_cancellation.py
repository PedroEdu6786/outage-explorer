"""Observable cooperative cancellation, stopped admission and mandatory joins."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from outage_explorer.application.ports.artifacts import ArtifactLimitError
from outage_explorer.infrastructure.connector_workers import BoundedConnectorWorkers


def test_external_cancellation_is_polled_without_waiting_for_task_completion():
    cancelled, entered, finishing, release = Event(), Event(), Event(), Event()
    workers = BoundedConnectorWorkers(2, cancelled)

    def cooperative():
        entered.set()
        assert cancelled.wait(3), "coordinator never propagated cancellation"
        finishing.set()
        assert release.wait(3)
        return "finished"

    with ThreadPoolExecutor(max_workers=1) as coordinator:
        future = coordinator.submit(workers.run, (cooperative,))
        assert entered.wait(3)
        cancelled.set()
        assert finishing.wait(3)
        assert not future.done(), "coordinator returned before joining its worker"
        release.set()
        with pytest.raises(ArtifactLimitError):
            future.result(timeout=3)


def test_deadline_propagates_to_running_cooperative_tasks_and_stops_admission(
    monkeypatch,
):
    from outage_explorer.infrastructure import connector_workers

    clock = [0.0]
    monkeypatch.setattr(connector_workers.time, "monotonic", lambda: clock[0])
    entered, finished = Event(), Event()
    workers = BoundedConnectorWorkers(2, elapsed_seconds=1)
    admissions = []

    def cooperative():
        entered.set()
        assert workers.cancelled.wait(3)
        finished.set()

    def tasks():
        yield cooperative
        assert entered.wait(3)
        clock[0] = 2.0
        admissions.append("yielded")
        yield lambda: admissions.append("started after deadline")

    with pytest.raises(ArtifactLimitError):
        workers.run(tasks())
    assert finished.is_set() and admissions == ["yielded"]


@pytest.mark.parametrize("count", [1, 2, 3])
def test_result_order_and_task_failure_remain_cooperative(count):
    workers = BoundedConnectorWorkers(count)
    assert workers.run((lambda: "first", lambda: "second", lambda: "third")) == (
        "first",
        "second",
        "third",
    )

    def failure():
        raise ValueError("controlled failure")

    with pytest.raises(ValueError):
        workers.run((failure,))
    assert workers.cancelled.is_set()


def test_deadline_polling_cancels_before_running_task_finishes(monkeypatch):
    from outage_explorer.infrastructure import connector_workers

    clock = [0.0]
    monkeypatch.setattr(connector_workers.time, "monotonic", lambda: clock[0])
    entered, finished = Event(), Event()
    workers = BoundedConnectorWorkers(2, elapsed_seconds=1)

    def blocked_until_cancelled():
        entered.set()
        assert workers.cancelled.wait(3), "deadline was not polled while waiting"
        finished.set()

    with ThreadPoolExecutor(max_workers=1) as coordinator:
        result = coordinator.submit(workers.run, (blocked_until_cancelled,))
        assert entered.wait(3)
        clock[0] = 2.0
        with pytest.raises(ArtifactLimitError):
            result.result(timeout=3)
    assert finished.is_set()
