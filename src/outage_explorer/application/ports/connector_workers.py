"""Injected bounded scheduling; application code owns operations and result order."""

from collections.abc import Callable, Iterable
from typing import Protocol, TypeVar

T = TypeVar("T")


class ConnectorWorkers(Protocol):
    def run(self, tasks: Iterable[Callable[[], T]]) -> tuple[T, ...]: ...
