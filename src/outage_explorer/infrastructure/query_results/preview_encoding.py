"""Reuse Phase 1 canonical value encoding and count the complete page envelope."""

from outage_explorer.application.errors import AnalyticalResourceError
from outage_explorer.domain.datasets import Column
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    EncodingLimit,
    UnsupportedValue,
    canonical_json,
    column_descriptors,
    encode_cell,
)


class PreviewEncoding:
    def __init__(self, bounds: EncodingBounds) -> None:
        self._bounds = bounds

    def columns(self, columns: tuple[Column, ...]) -> list[dict[str, object]]:
        result = column_descriptors(columns)
        if (
            len(columns) > self._bounds.max_columns
            or self.bytes(result) > self._bounds.max_schema_bytes
        ):
            raise AnalyticalResourceError("Preview schema resource limit")
        return result

    def row(
        self, columns: tuple[Column, ...], values: tuple[object, ...]
    ) -> list[object]:
        if len(columns) != len(values):
            raise AnalyticalResourceError("Invalid preview row")
        try:
            return [
                encode_cell(value, col.value_type, self._bounds)
                for col, value in zip(columns, values, strict=True)
            ]
        except (EncodingLimit, UnsupportedValue):
            raise AnalyticalResourceError("Preview encoding resource limit") from None

    def bytes(self, value: object) -> int:
        return len(canonical_json(value))
