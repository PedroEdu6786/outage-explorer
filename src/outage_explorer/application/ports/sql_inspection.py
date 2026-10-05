"""Parser-independent SQL inspection; inspection is neither authorization nor isolation."""

from dataclasses import dataclass
from typing import Protocol

from outage_explorer.domain.observations import Grain


class SqlRejected(ValueError):
    def __init__(self, code: str = "unsupported_sql") -> None:
        self.code = code
        super().__init__(
            "SQL is not supported" if code == "unsupported_sql" else "Invalid SQL"
        )


@dataclass(frozen=True)
class InspectedSql:
    sql: str
    grains: frozenset[Grain]
    reference_free: bool


class SqlInspector(Protocol):
    def inspect(self, sql: str) -> InspectedSql: ...
