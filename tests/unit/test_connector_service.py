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
