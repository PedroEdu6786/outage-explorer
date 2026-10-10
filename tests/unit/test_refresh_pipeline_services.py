"""Refresh responsibilities can be exercised without the execution coordinator."""

from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ResourceReport, ResourceRequest
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactRef,
    StoredObject,
)
from outage_explorer.application.ports.candidates import CandidateResult, GrainSummary
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.services.refresh_baseline import RestoreRefreshBaseline
from outage_explorer.application.services.refresh_candidate import (
    PrepareRefreshCandidate,
)
from outage_explorer.application.services.refresh_publication import (
    PrepareRefreshPublication,
)
from outage_explorer.domain.refresh import Interval, Quality, RefreshBounds

WINDOW = Interval(date(2026, 4, 2), date(2026, 10, 1))
BOUNDS = RefreshBounds(1000, 1000, 1000, 15, 1000, 100, 100, 100000, 366, 100000)


@pytest.fixture
def run():
    return Mock(
        id="run",
        base_generation_id=None,
        configuration=Mock(start=WINDOW.start, end=WINDOW.end),
    )


@pytest.fixture
def candidate():
    grains = ("national", "facility", "generator")
    return CandidateResult(
        "run",
        None,
        WINDOW,
        tuple(
            ArtifactRef(
                StoredObject(f"local/{g}.parquet", "a" * 64, 123),
                "resource",
                g,
                None,
                1,
            )
            for g in grains
        ),
        tuple(
            GrainSummary(
                g,
                Quality(1, 1, 0, 0, 0, ()),
                0,
                1,
                0,
                0,
                0,
                1,
                1,
                1,
                WINDOW.start,
                WINDOW.start,
            )
            for g in grains
        ),
        "candidate",
        ResourceRequest.contract_id,
        ResourceRequest.transformation_id,
    )


def report(candidate):
    return ResourceReport(
        "run", "run", WINDOW, "complete", "candidate_verified", candidate=candidate
    )


def test_initial_baseline_needs_no_resource_restore(run):
    store, publication, restore = Mock(), Mock(), Mock()
    publication.active_generation.return_value = None
    service = RestoreRefreshBaseline(store, publication, restore, BOUNDS)

    assert service.restore(run) is None
    restore.assert_not_called()
    store.get_run.assert_not_called()


def test_candidate_build_uses_frozen_admission_inputs(run):
    builder = Mock()
    service = PrepareRefreshCandidate(builder, Mock(), BOUNDS)

    assert service.build(run, None) is builder.run.return_value
    request = builder.run.call_args.args[0]
    assert request.interval == WINDOW
    assert request.run_id == request.generation_id == run.id
    assert request.bounds == BOUNDS
    assert request.prior is None


@pytest.mark.parametrize(
    "changes",
    [
        {"generation_id": "foreign"},
        {"base_generation_id": "foreign"},
        {"interval": Interval(WINDOW.start, WINDOW.start)},
        {"schema_version": "wrong"},
        {"contract_id": "wrong"},
        {"transformation_id": "wrong"},
        {"outcome": "retained_all_excluded"},
    ],
)
def test_candidate_verification_rejects_foreign_identity(run, candidate, changes):
    service = PrepareRefreshCandidate(Mock(), Mock(), BOUNDS)
    with pytest.raises(ArtifactError, match="Verified candidate identity mismatch"):
        service.verify(run, report(replace(candidate, **changes)))


def test_candidate_validates_coverage_and_report_identity(run, candidate):
    service = PrepareRefreshCandidate(Mock(), Mock(), BOUNDS)
    verified, coverage = service.verify(run, report(candidate))
    assert verified is candidate
    assert coverage == {
        g: (WINDOW.start, WINDOW.start) for g in ("national", "facility", "generator")
    }
    assert service.outcome(run, report(candidate), verified) == "publish"
    with pytest.raises(ArtifactError, match="Candidate identity mismatch"):
        service.outcome(run, replace(report(candidate), run_id="other"), verified)


def test_publication_prepares_durable_descriptors_without_database_access(
    run, candidate
):
    remote = tuple(
        replace(ref, object=replace(ref.object, key=f"remote/{ref.grain}.parquet"))
        for ref in candidate.resources
    )
    receipt = DurableResourceReceipt(
        "run", remote, WINDOW, candidate.contract_id, candidate.transformation_id, None
    )
    clock = Mock(now=lambda: datetime(2026, 10, 10, tzinfo=UTC))
    persist = Mock(return_value=receipt)
    service = PrepareRefreshPublication(
        Mock(return_value=remote), persist, BOUNDS, clock
    )

    assert service.persist(candidate) == receipt
    generation = service.generation(
        run,
        candidate,
        receipt,
        {ref.grain: (WINDOW.start, WINDOW.start) for ref in remote},
    )
    assert generation.id == generation.run_id == run.id
    assert tuple(item.object_key for item in generation.datasets) == tuple(
        ref.object.key for ref in remote
    )
    assert all(
        item.rows == 1 and item.end == WINDOW.start for item in generation.datasets
    )

    persist.return_value = replace(receipt, generation_id="other")
    with pytest.raises(ArtifactError, match="Durable receipt mismatch"):
        service.persist(candidate)
