"""Small bounded thread windows with cooperative cancellation and mandatory join."""

import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from threading import Event
from typing import TypeVar

from outage_explorer.application.ports.artifacts import ArtifactLimitError

T = TypeVar("T")


class BoundedConnectorWorkers:
    def __init__(
        self,
        workers: int = 1,
        cancelled: Event | None = None,
        elapsed_seconds: int | None = None,
    ) -> None:
        if type(workers) is not int or not 1 <= workers <= 3:
            raise ValueError("Connector workers must be between one and three")
        self.deadline = (
            None if elapsed_seconds is None else time.monotonic() + elapsed_seconds
        )
        self.workers = workers
        self.cancelled = Event() if cancelled is None else cancelled

    def check(self) -> None:
        if self.cancelled.is_set() or (
            self.deadline is not None and time.monotonic() >= self.deadline
        ):
            raise ArtifactLimitError("Connector work cancelled")

    def run(self, tasks: Iterable[Callable[[], T]]) -> tuple[T, ...]:
        iterator = iter(enumerate(tasks))
        results: dict[int, T] = {}
        if self.workers == 1:
            try:
                for index, task in iterator:
                    self.check()
                    results[index] = task()
                self.check()
            except BaseException:
                self.cancelled.set()
                raise
            return tuple(results[index] for index in range(len(results)))
        pool = ThreadPoolExecutor(
            max_workers=self.workers, thread_name_prefix="connector"
        )
        pending: dict[Future[T], int] = {}
        try:
            while True:
                self.check()
                while len(pending) < self.workers:
                    item = next(iterator, None)
                    if item is None:
                        break
                    index, task = item
                    pending[pool.submit(task)] = index
                if not pending:
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                # Inspect every completed result before admitting replacements.
                for future in done:
                    results[pending.pop(future)] = future.result()
            self.check()
        except BaseException:
            self.cancelled.set()
            for future in pending:
                future.cancel()
            raise
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        return tuple(results[index] for index in range(len(results)))
