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
from outage_explorer.application.ports.source import ROUTES
from outage_explorer.domain.observations import Grain
from outage_explorer.domain.refresh import RefreshInputError, RefreshLimitError


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


def quality_json(
    report: ResourceReport,
    coverage: Mapping[Grain, tuple[date, date]] | None = None,
) -> str:
    summaries = () if report.candidate is None else report.candidate.summaries
    models = {item.grain: item for item in summaries}
    sources = {item.grain: item for item in report.sources}
    datasets: list[dict[str, object]] = []
    for grain in ROUTES:
        model, source = models.get(grain), sources.get(grain)
        quality = None if model is None else model.quality
        if quality is not None and quality.received != (
            quality.selected + quality.excluded + quality.duplicate + quality.superseded
        ):
            raise ArtifactError("Disposition conservation failed")
        if (
            quality is not None
            and source is not None
            and quality.received != source.received
        ):
            raise ArtifactError("Source and model counts differ")
        reasons: Counter[str] = Counter()
        if quality is not None:
            for reason, count in quality.reason_counts:
                reasons[reason.code] += count
        datasets.append(
            {
                "dataset": grain,
                "coverage": None
                if coverage is None or grain not in coverage
                else {
                    "start_date": coverage[grain][0].isoformat(),
                    "end_date": coverage[grain][1].isoformat(),
                },
                "received": None if source is None else source.received,
                "selected": None if quality is None else quality.selected,
                "excluded": None if quality is None else quality.excluded,
                "duplicate": None if quality is None else quality.duplicate,
                "superseded": None if quality is None else quality.superseded,
                "exclusion_reasons": None if quality is None else dict(reasons),
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
        )
    result = dumps({"datasets": datasets}, separators=(",", ":"), sort_keys=True)
    if len(result.encode()) > 65536:
        raise ArtifactLimitError("Refresh quality report bound exceeded")
    return result
