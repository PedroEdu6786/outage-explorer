"""Publication guards over single dataset files, without PostgreSQL or S3."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ConnectorReport, ConnectorRequest
from outage_explorer.application.ports.artifacts import StoredObject
from outage_explorer.application.services.refresh_execution import RefreshExecution
from outage_explorer.domain.access import AnalyticalGrain
from outage_explorer.domain.publication import RefreshOwner, RunStatus
from outage_explorer.domain.refresh import RefreshBounds
from outage_explorer.infrastructure.parquet.storage import LocalParquetStore
from tests.integration.test_single_file_datasets import (
    BOUNDS as ARTIFACT_BOUNDS,
)
from tests.integration.test_single_file_datasets import INTERVAL, build_manifest

RUN = "11111111-1111-4111-8111-111111111111"
REFERENCE = StoredObject("a" * 64, "a" * 64, 100)
MODEL = RefreshBounds(1000, 1000, 1000, 15, 1000, 100, 100, 100000, 366, 100000)


def execution(tmp_path, change=None):
    verified = replace(
        build_manifest(LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)),
        generation_id=RUN,
        contract_id=ConnectorRequest.contract_id,
        transformation_id=ConnectorRequest.transformation_id,
        manifest_object=REFERENCE,
    )
    if change is not None:
        verified = change(verified)
    report = ConnectorReport(
        RUN,
        RUN,
        INTERVAL,
        "complete",
        "candidate_verified",
        manifest=REFERENCE,
        models=build_manifest(LocalParquetStore(tmp_path, ARTIFACT_BOUNDS)).summaries,
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
    connector.reopen.return_value = verified
    connector.persist.return_value = Mock(manifest=REFERENCE)

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
        (item.rows, item.start, item.end) == (5, date(2026, 9, 1), date(2026, 9, 5))
        for item in generation.datasets
    )
    store.finish.assert_not_called()


def faults():
    def public_dropped(m):
        return replace(m, public=m.public[:2])

    def public_foreign_grain(m):
        return replace(m, public=(m.public[0], m.public[0], m.public[2]))

    def public_count(m):
        return replace(m, public=(replace(m.public[0], row_count=4), *m.public[1:]))

    def modeled_count(m):
        return replace(m, modeled=(replace(m.modeled[1], row_count=4), *m.modeled[1:]))

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
