"""Durable lost-owner recovery without source retries or fabricated outcomes."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import pytest

from outage_explorer.application.errors import (
    AccessStoreError,
    RefreshBusyError,
    StaleRefreshOwnerError,
)
from outage_explorer.application.services.refresh_recovery import RefreshRecovery
from outage_explorer.domain.publication import RunStatus
from outage_explorer.infrastructure.postgresql.publication import (
    PostgresqlPublicationStore,
)
from outage_explorer.infrastructure.refresh_worker import RenewableRefreshLease
from tests.integration import test_data_api_postgresql as coordination
from tests.integration.test_refresh_execution import (
    RefreshS3,
    admit,
    composition,
    execute,
)

database = coordination.database
system = coordination.system


def test_claim_loss_before_first_fetch_is_interrupted_without_retry(
    system, database, tmp_path
):
    run = admit(system)
    owner = system[0].claim("lost-before-fetch", 60)
    coordination.expire(database)
    client = RefreshS3()
    process = composition(database, tmp_path, client=client)
    try:
        assert process.tick() is None
        recovered = system[0].get_run(run.id)
        assert recovered.status is RunStatus.INTERRUPTED
        assert recovered.failure == "interrupted"
        assert not client.calls
        assert process.tick() is None  # No automatic source work on later polls.
        with pytest.raises(StaleRefreshOwnerError):
            system[0].heartbeat(owner, 60)
        assert admit(system).id == run.id
        retry = admit(system, "b" * 16)
        assert retry.id != run.id
        assert process.tick().status is RunStatus.SUCCEEDED
    finally:
        process.close()


def test_healthy_claim_and_renewal_survive_reconciliation(system, database):
    run = admit(system)
    owner = system[0].claim("healthy", 1)
    lease = RenewableRefreshLease(system[0], seconds=1, renew_seconds=0.05)
    with lease(owner):
        # Controlled timer crosses the original lease, proving independent renewal.
        assert not Event().wait(1.1)
        assert RefreshRecovery(system[0]).execute(run.id).status is RunStatus.RUNNING
        lease.check()
    coordination.expire(database)
    assert RefreshRecovery(system[0]).execute(run.id).status is RunStatus.INTERRUPTED


def test_recovery_reads_history_after_later_generation_without_sources(
    system, database, tmp_path
):
    client = RefreshS3()
    first = execute(system, database, tmp_path, client=client)
    second = execute(system, database, tmp_path, client=client, key="b" * 16)
    active = system[0].active_generation()
    calls = tuple(client.calls)
    assert active.run_id == second.id
    for _ in range(2):
        recovered = RefreshRecovery(system[0]).execute(first.id)
        assert recovered.status is RunStatus.SUCCEEDED
        assert recovered.generation_id == first.id
        assert system[0].active_generation() == active
    assert tuple(client.calls) == calls


@pytest.mark.parametrize("mode", ["committed", "rollback", "unavailable"])
def test_verified_publication_commit_loss_reconciles_without_source_repeat(
    system, database, tmp_path, mode
):
    run = admit(system)
    process = composition(database, tmp_path)
    worker = process.tick.__self__
    faulty = PostgresqlPublicationStore(coordination.FaultPool(system[4], mode))
    worker.execution.publication = faulty
    # Use the good read port; fault occurs at publish, after verified S3 graph.
    faulty.active_generation = system[0].active_generation
    try:
        if mode == "unavailable":
            with pytest.raises(AccessStoreError):
                process.tick()
            assert (
                RefreshRecovery(system[0]).execute(run.id).status is RunStatus.SUCCEEDED
            )
        else:
            result = process.tick()
            assert result.status is (
                RunStatus.SUCCEEDED if mode == "committed" else RunStatus.INTERRUPTED
            )
        assert process.tick() is None
        assert (system[0].generation_for_run(run.id) is not None) == (
            mode != "rollback"
        )
    finally:
        process.close()


def test_unavailable_reconciliation_keeps_admission_occupied(
    system, database, tmp_path
):
    run = admit(system)
    system[0].claim("lost", 60)
    coordination.expire(database)
    with patch.object(system[0], "recover", side_effect=AccessStoreError("secret")):
        with pytest.raises(AccessStoreError):
            RefreshRecovery(system[0]).execute(run.id)
        with pytest.raises(RefreshBusyError):
            admit(system, "b" * 16)
    assert system[0].get_run(run.id).status is RunStatus.RUNNING
    assert RefreshRecovery(system[0]).execute(run.id).status is RunStatus.INTERRUPTED


def test_stale_worker_cannot_publish_after_recovery_during_source_work(
    system, database, tmp_path
):
    entered, released = Event(), Event()
    from tests.integration.test_connector_cli import Wire

    class BlockedWire(Wire):
        def handle_request(self, request):
            entered.set()
            assert released.wait(10)
            return super().handle_request(request)

    run = admit(system)
    client = RefreshS3()
    process = composition(database, tmp_path, BlockedWire(), client)
    try:
        with ThreadPoolExecutor() as pool:
            future = pool.submit(process.tick)
            assert entered.wait(5)
            coordination.expire(database)
            assert (
                RefreshRecovery(system[0]).execute(run.id).status
                is RunStatus.INTERRUPTED
            )
            released.set()
            with pytest.raises(StaleRefreshOwnerError):
                future.result(timeout=10)
        assert not any(operation == "put" for operation, _ in client.calls)
        assert system[0].active_generation() is None
    finally:
        released.set()
        process.close()


def test_forged_owner_is_rejected_before_artifact_or_source_access(
    system, database, tmp_path
):
    from outage_explorer.domain.publication import RefreshOwner
    from tests.integration.test_connector_cli import Wire

    run = admit(system)
    owner = system[0].claim("trusted-worker", 60)
    client, wire = RefreshS3(), Wire()
    process = composition(database, tmp_path, wire, client)
    try:
        with pytest.raises(StaleRefreshOwnerError):
            process.tick.__self__.execution.execute(
                RefreshOwner(run.id, "forged-owner", owner.epoch)
            )
        assert not wire.calls and not client.calls
    finally:
        process.close()
