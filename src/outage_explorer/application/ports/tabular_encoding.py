"""Canonical lossless wire encoding without an application engine dependency."""

from typing import Protocol

from outage_explorer.domain.datasets import Column


class TabularEncoding(Protocol):
    def columns(self, columns: tuple[Column, ...]) -> list[dict[str, object]]: ...
    def row(
        self, columns: tuple[Column, ...], values: tuple[object, ...]
    ) -> list[object]: ...
    def bytes(self, value: object) -> int: ...
