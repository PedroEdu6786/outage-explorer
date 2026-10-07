"""Ordering and failure semantics through application ports only."""

from dataclasses import replace
from datetime import date
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ConnectorRequest
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorReportError,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
    ArtifactRef,
    RepresentationError,
    StoredObject,
)
from outage_explorer.application.ports.candidates import (
    CandidateManifest,
    EvidenceBundle,
)
from outage_explorer.application.ports.source import (
    ROUTES,
    SourceError,
    SourceLimitError,
    SourceQuality,
)
from outage_explorer.application.services.connector import CreateConnectorCandidate
from outage_explorer.domain.refresh import (
    Interval,
    RefreshBounds,
    RefreshInputError,
    RefreshLimitError,
)

INTERVAL = Interval(date(2026, 9, 1), date(2026, 9, 2))
BOUNDS = RefreshBounds(100, 100, 100, 20, 1000, 100, 100, 100, 30, 1000)
REFERENCE = StoredObject("f" * 64, "f" * 64, 10)


def setup(prior=None, outcome="candidate"):
    events = []
    bundles = [
        EvidenceBundle(
            grain, INTERVAL, (ArtifactRef(REFERENCE, "raw", grain, None, 1),), ()
        )
        for grain in ROUTES
    ]
    qualities = [
        SourceQuality(
            grain, INTERVAL, 1, ("1",), False, False, (date(2026, 9, 1),), (), ()
        )
        for grain in ROUTES
    ]
    sources = [Mock(quality=quality) for quality in qualities]
    factory = Mock(
        side_effect=lambda request: (
            events.append(request.grain),
            sources[list(ROUTES).index(request.grain)],
        )[1]
    )
    evidence = Mock()
    evidence.write.side_effect = bundles
    manifest = CandidateManifest(
        "generation",
        None,
        INTERVAL,
        tuple(bundles),
        (),
        (),
        (),
        (),
        (),
        (),
        (),
        outcome,
        "contract",
        "transform",
        manifest_object=REFERENCE,
    )
    evidence.reopen.return_value = manifest
    builder = Mock()
    builder.build.side_effect = lambda *args: (events.append("modeling"), manifest)[1]
    reports = Mock()
    service = CreateConnectorCandidate(factory, evidence, builder, reports)
    request = ConnectorRequest(INTERVAL, "run", "generation", BOUNDS, prior)
    return service, request, sources, evidence, builder, reports, events, manifest


def test_three_terminal_routes_precede_model_and_reopen_precedes_success():
    service, request, sources, evidence, builder, reports, events, candidate = setup()
    result = service.run(request)
    assert events == ["national", "facility", "generator", "modeling"]
    assert result.report.outcome == "candidate_verified" and result.report_written
    assert result.report.manifest == REFERENCE and not result.report.published
    evidence.reopen.assert_called_once_with(REFERENCE, BOUNDS)
    builder.verify.assert_called_once_with(candidate, BOUNDS)
    reports.finish.assert_called_once_with(result.report)


def test_invalid_prior_fails_before_source_factory():
    service, request, _, evidence, builder, _, events, _ = setup(REFERENCE)
    evidence.reopen.side_effect = ArtifactError("unsafe upstream text")
    result = service.run(request)
    assert result.report.error == "prior_integrity" and events == []
    builder.build.assert_not_called()
    assert "unsafe" not in repr(result)


@pytest.mark.parametrize(
    "quality",
    [None, SourceQuality("national", INTERVAL, 2, ("2",), False, False, (), (), ())],
)
def test_missing_or_inconsistent_terminal_quality_prevents_modeling(quality):
    service, request, sources, _, builder, _, events, _ = setup()
    sources[0].quality = quality
    result = service.run(request)
    assert result.report.error == "retrieval" and events == ["national"]
    builder.build.assert_not_called()


@pytest.mark.parametrize(
    "error,code",
    [
        (SourceError("secret"), "retrieval"),
        (SourceLimitError("secret"), "resource"),
        (ArtifactLimitError("secret"), "resource"),
        (RefreshLimitError("secret"), "resource"),
        (RepresentationError("secret"), "representation"),
        (ArtifactError("secret"), "artifact_integrity"),
        (RefreshInputError("secret"), "unusable_input"),
        (KeyboardInterrupt(), "interrupted"),
        (RuntimeError("secret"), "internal"),
    ],
)
def test_failures_are_safe_codes_not_exclusions(error, code):
    service, request, _, evidence, _, _, _, _ = setup()
    evidence.write.side_effect = error
    result = service.run(request)
    assert result.report.error == code
    assert result.report.outcome == "failed" and result.report.manifest is None
    assert result.report.models == () and "secret" not in repr(result)


def test_initial_unusable_grain_is_failure_and_all_excluded_is_distinct():
    service, request, _, _, builder, _, _, _ = setup()
    builder.build.side_effect = RefreshInputError("Initial load requires every grain")
    assert service.run(request).report.error == "unusable_input"
    service, request, _, _, _, _, _, _ = setup(outcome="retained_all_excluded")
    result = service.run(request)
    assert (
        result.report.outcome == "retained_all_excluded" and not result.report.published
    )


def test_report_failure_cannot_claim_completion():
    service, request, _, _, _, reports, _, _ = setup()
    reports.finish.side_effect = ConnectorReportError("secret")
    result = service.run(request)
    assert result.report.error == "report" and result.report.outcome == "failed"
    assert result.report.manifest is None and not result.report_written


def test_progress_failure_precedes_retrieval():
    service, request, _, _, _, reports, events, _ = setup()
    reports.progress.side_effect = ConnectorReportError("secret")
    result = service.run(request)
    assert result.report.error == "report" and events == []


def test_missing_or_different_persisted_manifest_cannot_claim_success():
    service, request, _, evidence, _, _, _, manifest = setup()
    evidence.reopen.return_value = replace(manifest, generation_id="different")
    assert service.run(request).report.error == "artifact_integrity"


def test_direct_request_validates_bounds_without_ports():
    with pytest.raises(ConnectorConfigurationError):
        ConnectorRequest(
            INTERVAL, "run", "generation", replace(BOUNDS, interval_days=1)
        )


def test_diagnostic_failure_does_not_change_candidate_outcome():
    service, request, _, _, builder, _, _, _ = setup()
    observer = Mock()
    observer.emit.side_effect = RuntimeError("diagnostics unavailable")
    service.events = observer
    result = service.run(request)
    assert result.report.outcome == "candidate_verified"
    builder.verify.assert_called_once()


def test_failure_event_contains_only_safe_stage_and_code():
    service, request, _, evidence, _, _, _, _ = setup(REFERENCE)
    observer = Mock()
    service.events = observer
    evidence.reopen.side_effect = ArtifactError("secret upstream error")
    result = service.run(request)
    assert result.report.error == "prior_integrity"
    observer.emit.assert_any_call(
        "candidate_failed", run="run", stage="prior", code="prior_integrity"
    )
    assert "secret upstream error" not in repr(observer.emit.call_args_list)


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
