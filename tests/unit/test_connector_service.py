"""Ordering and failure semantics through resource application ports."""

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import ConnectorReportError
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    RepresentationError,
    StoredObject,
)
from outage_explorer.application.ports.source import ROUTES, SourceQuality
from outage_explorer.domain.refresh import Interval, RefreshBounds

INTERVAL = Interval(date(2026, 9, 1), date(2026, 9, 2))
BOUNDS = RefreshBounds(100, 100, 100, 20, 1000, 100, 100, 100, 30, 1000)


def resource_setup(prior=None):
    from outage_explorer.application.dto import ResourceRequest
    from outage_explorer.application.ports.candidates import (
        CandidateResult,
        GrainSummary,
        TransientInput,
    )
    from outage_explorer.application.services.connector import CreateResourceCandidate
    from outage_explorer.domain.refresh import Quality

    qualities = tuple(
        SourceQuality(grain, INTERVAL, 1, ("1",), False, False, (), (), ())
        for grain in ROUTES
    )
    sources = [Mock(quality=quality) for quality in qualities]
    factory = Mock(side_effect=sources)
    local = Mock()
    local.collect_resources.side_effect = [
        TransientInput(
            grain,
            INTERVAL,
            (Mock(),),
            2,
            100,
            "run",
            "eia-nuclear-observations-v1",
            "outage-share-exact-v1",
        )
        for grain in ROUTES
    ]
    resources = tuple(
        ArtifactRef(StoredObject(char * 64, char * 64, 10), "resource", grain, None, 1)
        for grain, char in zip(ROUTES, "abc", strict=True)
    )
    summaries = tuple(
        GrainSummary(
            grain,
            Quality(1, 1, 0, 0, 0, ()),
            0,
            1,
            0,
            0,
            0,
            1,
            1,
            1,
            INTERVAL.start,
            INTERVAL.start,
        )
        for grain in ROUTES
    )
    candidate = CandidateResult(
        "generation",
        None if prior is None else prior.generation_id,
        INTERVAL,
        resources,
        summaries,
        "candidate",
        "eia-nuclear-observations-v1",
        "outage-share-exact-v1",
    )
    builder, reports = Mock(), Mock()
    builder.build_resources.return_value = candidate
    request = ResourceRequest(INTERVAL, "run", "generation", BOUNDS, prior)
    service = CreateResourceCandidate(factory, local, builder, reports)
    return service, request, sources, factory, local, builder, reports, candidate


def test_resource_coordinator_uses_injected_builder_without_manifest_graph():
    service, request, _, factory, local, builder, reports, candidate = resource_setup()
    result = service.run(request)
    assert (
        result.report.candidate == candidate
        and result.report.outcome == "candidate_verified"
    )
    assert result.report_written and not result.report.published
    assert factory.call_count == local.collect_resources.call_count == 3
    builder.verify_resources.assert_called_once_with(candidate, BOUNDS)
    reports.finish.assert_called_once_with(result.report)
    local.reopen.assert_not_called()
    local.graph.assert_not_called()


def test_resource_prior_failure_precedes_source_access():
    _, _, _, _, _, _, _, candidate = resource_setup()
    service, request, _, factory, local, builder, _, _ = resource_setup(
        replace(candidate.baseline, generation_id="prior")
    )
    local.verify_baseline.side_effect = ArtifactError("private bad baseline")
    result = service.run(request)
    assert result.report.error == "prior_integrity" and result.report.candidate is None
    factory.assert_not_called()
    builder.build_resources.assert_not_called()


@pytest.mark.parametrize(
    "fault", ["quality", "identity", "report", "representation", "cancellation"]
)
def test_resource_coordinator_failure_never_returns_candidate(fault):
    service, request, sources, _, _, builder, reports, candidate = resource_setup()
    if fault == "quality":
        sources[0].quality = None
        expected = "retrieval"
    elif fault == "identity":
        builder.build_resources.return_value = replace(
            candidate, generation_id="forged"
        )
        expected = "artifact_integrity"
    elif fault == "report":
        reports.finish.side_effect = ConnectorReportError("private disk detail")
        expected = "report"
    elif fault == "representation":
        builder.build_resources.side_effect = RepresentationError(
            "private decimal detail"
        )
        expected = "representation"
    else:
        builder.build_resources.side_effect = KeyboardInterrupt()
        expected = "interrupted"
    result = service.run(request)
    assert result.report.outcome == "failed" and result.report.error == expected
    assert result.report.candidate is None
    assert result.report_written == (fault != "report")
    assert "private" not in repr(result)


@pytest.mark.parametrize("fault", ["grain", "interval"])
def test_resource_input_matches_requested_route_before_modeling(fault):
    service, request, _, _, local, builder, _, _ = resource_setup()
    collected = list(local.collect_resources.side_effect)
    first = collected[0]
    collected[0] = replace(
        first,
        **(
            {"grain": "facility"}
            if fault == "grain"
            else {"interval": Interval(date(2026, 8, 1), date(2026, 8, 2))}
        ),
    )
    local.collect_resources.side_effect = collected
    result = service.run(request)
    assert result.report.error == "artifact_integrity"
    assert result.report.stage == "retrieval" and result.report.candidate is None
    builder.build_resources.assert_not_called()
