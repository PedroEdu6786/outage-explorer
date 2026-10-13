"""Bounded status projections; dispositions and reason occurrences stay distinct."""

from collections import Counter
from collections.abc import Mapping
from datetime import date
from json import dumps

from outage_explorer.application.dto import ResourceReport
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorFailure,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    RepresentationError,
)
from outage_explorer.application.ports.candidates import GrainSummary
from outage_explorer.application.ports.source import ROUTES, SourceQuality
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import Quality, RefreshInputError, RefreshLimitError


def safe_failure(error: Exception) -> ConnectorFailure:
    if isinstance(error, (ArtifactLimitError, RefreshLimitError)):
        return "resource"
    if isinstance(error, ConnectorConfigurationError):
        return "configuration"
    if isinstance(error, RepresentationError):
        return "representation"
    if isinstance(error, RefreshInputError):
        return "unusable_input"
    if isinstance(error, (ArtifactError, OSError)):
        return "artifact_integrity"
    return "internal"


def _require_consistent_counts(
    quality: Quality | None, source: SourceQuality | None
) -> None:
    if quality is None:
        return
    dispositions = (
        quality.selected + quality.excluded + quality.duplicate + quality.superseded
    )
    if quality.received != dispositions:
        raise ArtifactError("Disposition conservation failed")
    if source is not None and quality.received != source.received:
        raise ArtifactError("Source and model counts differ")


def _exclusion_reasons(quality: Quality | None) -> dict[str, int] | None:
    if quality is None:
        return None
    reasons: Counter[str] = Counter()
    for reason, count in quality.reason_counts:
        reasons[reason.code] += count
    return dict(reasons)


def _coverage_payload(
    grain: Grain, coverage: Mapping[Grain, tuple[date, date]] | None
) -> dict[str, str] | None:
    if coverage is None or grain not in coverage:
        return None
    start, end = coverage[grain]
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def _dataset_payload(
    grain: Grain,
    model: GrainSummary | None,
    source: SourceQuality | None,
    coverage: Mapping[Grain, tuple[date, date]] | None,
) -> dict[str, object]:
    quality = None if model is None else model.quality
    _require_consistent_counts(quality, source)
    return {
        "dataset": grain,
        "coverage": _coverage_payload(grain, coverage),
        "received": None if source is None else source.received,
        "selected": None if quality is None else quality.selected,
        "excluded": None if quality is None else quality.excluded,
        "duplicate": None if quality is None else quality.duplicate,
        "superseded": None if quality is None else quality.superseded,
        "exclusion_reasons": _exclusion_reasons(quality),
        "retained_invalid": None if model is None else model.retained_invalid,
        "retained_absent": None if model is None else model.retained_absent,
        "carried_outside_interval": None
        if model is None
        else model.carried_outside_interval,
        "output": None if model is None else model.candidate_count,
        "observed_entities": None if model is None else model.observed_entities,
        "observed_dates": None if model is None else model.observed_dates,
        "usable_dates": None if model is None else model.usable_dates,
    }


def quality_json(
    report: ResourceReport,
    coverage: Mapping[Grain, tuple[date, date]] | None = None,
) -> str:
    summaries = () if report.candidate is None else report.candidate.summaries
    models = {item.grain: item for item in summaries}
    sources = {item.grain: item for item in report.sources}
    datasets = [
        _dataset_payload(grain, models.get(grain), sources.get(grain), coverage)
        for grain in ROUTES
    ]
    result = dumps({"datasets": datasets}, separators=(",", ":"), sort_keys=True)
    if len(result.encode()) > 65536:
        raise ArtifactLimitError("Refresh quality report bound exceeded")
    return result
