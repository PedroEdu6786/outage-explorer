"""Bound nested values before Arrow allocation."""

import math
from datetime import date, datetime
from decimal import Decimal

from outage_explorer.application.ports.artifacts import (
    ArtifactBounds,
    ArtifactError,
    ArtifactLimitError,
)


def value_size(value: object, bounds: ArtifactBounds, depth: int = 0) -> int:
    """Bound recursively before Arrow/JSON allocation; approximate Python payload."""
    if depth > bounds.json_depth:
        raise ArtifactLimitError("Exceeded nested value depth")
    if isinstance(value, str):
        return _text_size(value, bounds)
    if value is None or isinstance(value, (bool, date, datetime, Decimal)):
        return 32
    if type(value) is int:
        if value.bit_length() > bounds.field_bytes * 3:
            raise ArtifactLimitError("Exceeded integer bytes")
        return max(8, value.bit_length())
    if type(value) is float:
        if not math.isfinite(value):
            raise ArtifactError("JSON values must be finite")
        return 16
    if isinstance(value, dict):
        return _object_size(value, bounds, depth)
    if isinstance(value, (list, tuple)):
        return _sequence_size(value, bounds, depth)
    raise ArtifactError("Unsupported artifact value")


def _text_size(value: str, bounds: ArtifactBounds) -> int:
    if len(value) > bounds.field_bytes:
        raise ArtifactLimitError("Exceeded field bytes")
    encoded_bytes = len(value.encode("utf-8"))
    if encoded_bytes > bounds.field_bytes:
        raise ArtifactLimitError("Exceeded field bytes")
    return encoded_bytes + 8


def _object_size(
    value: dict[object, object], bounds: ArtifactBounds, depth: int
) -> int:
    if len(value) > bounds.row_group_bytes:
        raise ArtifactLimitError("Exceeded collection size")
    size = 8
    for key, item in value.items():
        if not isinstance(key, str):
            raise ArtifactError("Object keys must be strings")
        size += value_size(key, bounds, depth + 1)
        size += value_size(item, bounds, depth + 1)
        if size > bounds.row_group_bytes:
            raise ArtifactLimitError("Exceeded row-group bytes")
    return size


def _sequence_size(
    value: list[object] | tuple[object, ...], bounds: ArtifactBounds, depth: int
) -> int:
    if len(value) > bounds.row_group_bytes:
        raise ArtifactLimitError("Exceeded collection size")
    size = 8
    for item in value:
        size += value_size(item, bounds, depth + 1)
        if size > bounds.row_group_bytes:
            raise ArtifactLimitError("Exceeded row-group bytes")
    return size
