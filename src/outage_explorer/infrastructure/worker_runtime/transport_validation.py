"""Shared validation for the parent side of the worker transport."""

from datetime import date

from outage_explorer.application.ports.execution import PreviewRead


class _Invalid(ValueError):
    pass


def _object(value: object, fields: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise _Invalid()
    return value


def preview_key(value: object, request: PreviewRead) -> tuple[str, ...]:
    width = 1 + sum(
        c.name in {"facility", "generator"} for c in request.dataset.columns
    )
    if (
        not isinstance(value, (tuple, list))
        or len(value) != width
        or any(not isinstance(v, str) or not v for v in value)
    ):
        raise _Invalid()
    if date.fromisoformat(value[0]).isoformat() != value[0]:
        raise _Invalid()
    return tuple(value)
