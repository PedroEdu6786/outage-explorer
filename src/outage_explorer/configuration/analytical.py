"""Analytical HTTP enablement and isolated worker limits."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class DataHttpSettings:
    enabled: bool = False


def data_http_settings(environment: Mapping[str, str]) -> DataHttpSettings:
    value = environment.get("OUTAGE_DATA_HTTP_ENABLED", "false")
    if value not in {"true", "false"}:
        raise ValueError("Invalid data HTTP enablement")
    return DataHttpSettings(value == "true")


@dataclass(frozen=True)
class AnalyticalWorkerSettings:
    """Internal v1 image limits; changes require a new matching image/evidence."""

    preparation_seconds: int = 30
    overall_seconds: int = 40
    execution_seconds: int = 10
    memory_bytes: int = 134_217_728
    temporary_bytes: int = 16_777_216
    output_bytes: int = 1_048_576
    max_cell_bytes: int = 1_048_576
    max_depth: int = 16
    max_nested_items: int = 10_000
    max_columns: int = 100
    max_schema_bytes: int = 65_536

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Invalid analytical worker limits")
        if self.execution_seconds > 10 or self.output_bytes > 1_048_576:
            raise ValueError("Analytical worker limits exceed accepted caps")
