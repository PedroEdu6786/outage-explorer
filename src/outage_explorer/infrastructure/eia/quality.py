"""Observed source coverage and totals, separate from modeling quality."""

from datetime import date

from outage_explorer.application.ports.source import (
    SourceError,
    SourceQuality,
    SourceRequest,
)


def reconcile(
    request: SourceRequest,
    received: int,
    totals: tuple[str, ...],
    dates: set[date],
    entities: set[tuple[str, ...]],
) -> SourceQuality:
    if not received:
        raise SourceError("empty_source")
    normalized = tuple(total.lstrip("0") or "0" for total in totals)
    changed = len(set(normalized)) > 1
    mismatch = any(total != str(received) for total in normalized)
    if (changed or mismatch) and request.grain != "facility":
        raise SourceError("Source totals inconsistent with received rows")
    diagnostics = ("facility_total_diagnostic_v1",) if changed or mismatch else ()
    return SourceQuality(
        request.grain,
        request.interval,
        received,
        totals,
        changed,
        mismatch,
        tuple(sorted(dates)),
        tuple(sorted(entities)),
        diagnostics,
    )
