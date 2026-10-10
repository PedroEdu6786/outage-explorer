"""Publication guards over single dataset files, without PostgreSQL or S3."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ResourceReport, ResourceRequest
from outage_explorer.application.errors import AccessStoreError, StaleRefreshOwnerError
from outage_explorer.application.ports.candidates import ResourceBaseline
from outage_explorer.application.ports.connector import DurableResourceReceipt
from outage_explorer.application.services.refresh_execution import RefreshExecution
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import RefreshOwner, RunStatus
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_connector_parquet import WINDOW as INTERVAL
from tests.integration.test_resource_candidates import build
from tests.integration.test_single_file_datasets import (
    BOUNDS as ARTIFACT_BOUNDS,
)

RUN = "11111111-1111-4111-8111-111111111111"
MODEL = RefreshBounds(1000, 1000, 1000, 15, 1000, 100, 100, 100000, 366, 100000)


def execution(tmp_path, change=None):
    verified = replace(
        build(LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)),
        generation_id=RUN,
        contract_id=ResourceRequest.contract_id,
        transformation_id=ResourceRequest.transformation_id,
    )
    if change is not None:
        verified = change(verified)
    report = ResourceReport(
        RUN, RUN, INTERVAL, "complete", "candidate_verified", candidate=verified
    )
    run = Mock(
        status=RunStatus.RUNNING,
        epoch=1,
        id=RUN,
        base_generation_id=None,
        configuration=Mock(start=INTERVAL.start, end=INTERVAL.end),
    )
    store, publication = Mock(), Mock()
    store.get_run.return_value = run
    publication.active_generation.return_value = None
    connector = Mock(
        bounds=MODEL,
        clock=Mock(now=lambda: datetime(2026, 10, 6, tzinfo=UTC)),
    )
    connector.candidate.run.return_value = Mock(report=report, report_written=True)
    filenames = {
        "national": "national",
        "facility": "facilities",
        "generator": "generators",
    }
    addresses = tuple(
        replace(
            ref,
            object=replace(
                ref.object,
                key=f"connector/generations/{RUN}/{filenames[ref.grain]}.parquet",
            ),
        )
        for ref in verified.resources
    )
    connector.addresses.return_value = addresses
    connector.persist.side_effect = lambda *_: DurableResourceReceipt(
        RUN, addresses, INTERVAL, verified.contract_id, verified.transformation_id, None
    )

    @contextmanager
    def factory(_run, _owner):
        yield connector

    return (
        RefreshExecution(store, publication, factory),
        store,
        publication,
        connector,
    )


OWNER = RefreshOwner(RUN, "worker", 1)


def test_coverage_and_rows_come_from_verified_summaries_of_single_files(tmp_path):
    service, store, publication, connector = execution(tmp_path)
    service.execute(OWNER)
    connector.persist.assert_called_once()
    generation = publication.publish.call_args.args[1]
    assert {item.grain for item in generation.datasets} == set(AnalyticalGrain)
    assert all(
        (item.rows, item.start, item.end) == (1, date(2026, 9, 2), date(2026, 9, 2))
        for item in generation.datasets
    )
    store.finish.assert_not_called()


def faults():
    def public_dropped(m):
        return replace(m, resources=m.resources[:2])

    def public_foreign_grain(m):
        return replace(m, resources=(m.resources[0], m.resources[0], m.resources[2]))

    def public_count(m):
        return replace(
            m, resources=(replace(m.resources[0], row_count=4), *m.resources[1:])
        )

    def modeled_count(m):
        return replace(
            m, resources=(replace(m.resources[1], row_count=4), *m.resources[1:])
        )

    def no_coverage(m):
        first = replace(m.summaries[0], first_period=None, last_period=None)
        return replace(m, summaries=(first, *m.summaries[1:]))

    return [
        public_dropped,
        public_foreign_grain,
        public_count,
        modeled_count,
        no_coverage,
    ]


@pytest.mark.parametrize("fault", faults(), ids=lambda fault: fault.__name__)
def test_missing_mutated_or_foreign_dataset_files_are_never_persisted_or_published(
    tmp_path, fault
):
    service, store, publication, connector = execution(tmp_path, fault)
    service.execute(OWNER)
    connector.persist.assert_not_called()
    publication.publish.assert_not_called()
    assert store.finish.call_args.args[1] is RunStatus.FAILED


@pytest.mark.parametrize("error", [AccessStoreError, StaleRefreshOwnerError])
def test_ownership_check_failure_stops_before_baseline_or_source_access(
    tmp_path, error
):
    service, store, publication, connector = execution(tmp_path)
    store.progress.side_effect = error("Ownership unavailable")

    with pytest.raises(error):
        service.execute(OWNER)

    publication.active_generation.assert_not_called()
    connector.candidate.run.assert_not_called()
    connector.persist.assert_not_called()
    publication.publish.assert_not_called()
    store.finish.assert_not_called()


def test_persistence_failure_records_failure_without_publishing(tmp_path):
    service, store, publication, connector = execution(tmp_path)
    connector.persist.side_effect = RuntimeError("Upload failed")

    service.execute(OWNER)

    publication.publish.assert_not_called()
    store.finish.assert_called_once()
    assert store.finish.call_args.args[1] is RunStatus.FAILED
    assert store.finish.call_args.args[2] is not None


def test_mismatched_durable_receipt_cannot_publish(tmp_path):
    service, store, publication, connector = execution(tmp_path)
    original_receipt = connector.persist.side_effect
    connector.persist.side_effect = lambda *args: replace(
        original_receipt(*args), generation_id="foreign-generation"
    )

    service.execute(OWNER)

    publication.publish.assert_not_called()
    assert store.finish.call_args.args[1] is RunStatus.FAILED


@pytest.mark.parametrize(
    "error", [RuntimeError, AccessStoreError, StaleRefreshOwnerError]
)
def test_publication_error_propagates_without_overwriting_uncertain_outcome(
    tmp_path, error
):
    service, store, publication, connector = execution(tmp_path)
    publication.publish.side_effect = error("Publication response unavailable")

    with pytest.raises(error):
        service.execute(OWNER)

    connector.persist.assert_called_once()
    publication.publish.assert_called_once()
    store.finish.assert_not_called()


def test_cleanup_error_after_publication_cannot_mark_run_failed(tmp_path):
    service, store, publication, connector = execution(tmp_path)
    original_factory = service.factory

    @contextmanager
    def cleanup_failure(run, owner):
        with original_factory(run, owner) as composed_connector:
            yield composed_connector
        raise RuntimeError("Cleanup failed after publication")

    service.factory = cleanup_failure

    with pytest.raises(RuntimeError, match="Cleanup failed"):
        service.execute(OWNER)

    connector.persist.assert_called_once()
    publication.publish.assert_called_once()
    store.finish.assert_not_called()


def test_changed_baseline_stops_before_source_work(tmp_path):
    service, store, publication, connector = execution(tmp_path)
    publication.active_generation.return_value = Mock(id="unexpected-generation")

    with pytest.raises(StaleRefreshOwnerError, match="Pinned base changed"):
        service.execute(OWNER)

    connector.restore.assert_not_called()
    connector.candidate.run.assert_not_called()
    connector.persist.assert_not_called()
    publication.publish.assert_not_called()
    store.finish.assert_not_called()


def test_all_excluded_refresh_restores_baseline_without_persisting_or_publishing(
    tmp_path,
):
    service, store, publication, connector = execution(tmp_path)
    service.execute(OWNER)
    base = replace(
        publication.publish.call_args.args[1],
        id="previous-generation",
        run_id="previous-run",
    )
    publication.reset_mock()
    connector.reset_mock()
    publication.active_generation.return_value = base
    run = store.get_run.return_value
    run.base_generation_id = base.id
    base_run = Mock(generation_id=base.id, configuration=run.configuration)
    store.get_run.side_effect = lambda run_id: (
        base_run if run_id == base.run_id else run
    )
    connector.restore.side_effect = lambda receipt, _bounds: ResourceBaseline(
        receipt.generation_id,
        receipt.resources,
        receipt.contract_id,
        receipt.transformation_id,
    )
    report = connector.candidate.run.return_value.report
    retained = replace(
        report.candidate,
        base_generation_id=base.id,
        outcome="retained_all_excluded",
        summaries=tuple(
            replace(
                summary,
                quality=replace(
                    summary.quality,
                    selected=0,
                    excluded=summary.quality.received,
                    duplicate=0,
                    superseded=0,
                ),
            )
            for summary in report.candidate.summaries
        ),
    )
    connector.candidate.run.return_value.report = replace(
        report, outcome="retained_all_excluded", candidate=retained
    )

    service.execute(OWNER)

    connector.restore.assert_called_once()
    request = connector.candidate.run.call_args.args[0]
    assert request.prior.generation_id == base.id
    assert request.interval == INTERVAL
    connector.verify.assert_called_once()
    connector.persist.assert_not_called()
    publication.publish.assert_not_called()
    store.finish.assert_called_once()
    assert store.finish.call_args.args[1] is RunStatus.RETAINED
