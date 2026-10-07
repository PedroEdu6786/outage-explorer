"""PostgreSQL/Parquet flows and portable injected ports. No OS isolation claims."""

import pickle
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import psycopg
import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    AnalyticalResourceError,
    DataUnavailableError,
    ForbiddenError,
    InvalidRequestError,
    PreviewCapacityError,
    PreviewUnavailableError,
    RuntimeUnavailableError,
    UnauthenticatedError,
)
from outage_explorer.application.ports.execution import ExecutionBounds, PreviewRows
from outage_explorer.application.services.catalog import CatalogService
from outage_explorer.application.services.preview import PreviewService
from outage_explorer.domain.access import AnalyticalGrain, Role
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.publication import (
    DatasetSummary,
    ResourcePublishedGeneration,
)
from outage_explorer.infrastructure.local_cache.modeled import (
    CacheBounds,
    VerifiedResourceCache,
)
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    canonical_json,
)
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.query_results.previews import (
    BoundedPreviewSequences,
    PreviewBounds,
)
from outage_explorer.infrastructure.s3.resources import S3ResourceStore
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from tests.integration import test_connector_cli as connector
from tests.integration import test_data_api_postgresql as coordination
from tests.integration import test_refresh_execution as resource_refresh
from tests.integration.test_connector_cli import ARTIFACT, row
from tests.integration.test_refresh_execution import RefreshS3, execute

database = coordination.database

system = resource_refresh.system

EXECUTION = ExecutionBounds(20, 30, 128 * 1024**2, 32 * 1024**2, 1024**2)
ENCODING = EncodingBounds(1024**2, 16, 10000, 100, 65536)
CACHE = CacheBounds(64 * 1024**2, 1000, 10000, 20)
METADATA = PreviewBounds(10, 30, 1024**2, 4096)


class Clock:
    def __init__(self):
        self.value = datetime.now(UTC)

    def now(self):
        return self.value


class ControlledRuntime:
    """Fixture subprocess ends/reaps before return. Not a reviewed launcher."""

    def __init__(self):
        self.calls = []
        self.reaps = 0

    def preview(self, request, bounds, deadline):
        self.calls.append(request)
        result = subprocess.run(
            [sys.executable, "tests/fixtures/data_api/preview_worker.py"],
            input=pickle.dumps((request, bounds)),
            capture_output=True,
            timeout=10,
            env={"PYTHONPATH": str(Path("src").resolve())},
        )
        assert result.returncode == 0, result.stderr.decode()
        output = pickle.loads(result.stdout)
        if isinstance(output, Exception):
            raise output
        return output

    def terminate_and_reap(self):
        self.reaps += 1


@pytest.fixture
def browsing(system, database, tmp_path):
    client = RefreshS3()
    identifiers = ["001", "01", "1", "A", "Z", "a", "é", "😀"]
    values = {
        "national": [
            row("national", period=day) for day in ("2026-09-01", "2026-09-02")
        ],
        "facility": [row("facility", facility=value) for value in identifiers],
        "generator": [
            row("generator", generator=f"{value:04}") for value in range(503)
        ],
    }
    result = execute(system, database, tmp_path / "refresh", values, client)
    assert result.status.value == "succeeded", (result.failure, result.quality_json)
    objects = S3ResourceStore(client, "test-bucket", "connector/", ARTIFACT)
    cache = VerifiedResourceCache(tmp_path / "cache", objects, ARTIFACT, CACHE)
    runtime = ControlledRuntime()
    launcher = VerifiedLauncher(
        EXECUTION,
        runtime,
        evidence="controlled test injection only; not Linux approval",
    )
    clock = Clock()
    sequences = BoundedPreviewSequences(
        clock, METADATA, b"synthetic-test-cursor-key-32-bytes!"
    )
    encoding = PreviewEncoding(ENCODING)
    service = PreviewService(
        system[1]._access,
        system[0],
        cache,
        launcher,
        sequences,
        encoding,
        response_bytes=1024**2,
    )
    yield service, cache, sequences, clock, runtime, client, values
    sequences.close()


@pytest.mark.parametrize("role", list(Role))
def test_catalog_roles_and_public_columns_before_data(system, browsing, role):
    catalog = CatalogService(system[1]._access, system[0]).list(system[2][role])
    assert [entry.dataset.id for entry in catalog] == (
        ["national"]
        if role is Role.VIEWER
        else ["national", "facilities", "generators"]
    )
    assert all(
        entry.generation_id == system[0].active_generation().id for entry in catalog
    )
    assert all(
        "origin" not in [col.name for col in entry.dataset.columns] for entry in catalog
    )
    service, _, _, _, runtime, _, _ = browsing
    if role is Role.VIEWER:
        with pytest.raises(ForbiddenError):
            service.page(system[2][role], "facilities")
        assert not runtime.calls
    else:
        assert service.page(system[2][role], "facilities")["rows"]


def test_exact_national_precision_public_projection_and_inclusive_dates(
    system, browsing
):
    service = browsing[0]
    token = system[2][Role.VIEWER]
    page = service.page(token, "national")
    assert [values[0] for values in page["rows"]] == ["2026-09-02", "2026-09-01"]
    columns = [col["name"] for col in page["columns"]]
    assert columns == [col.name for col in PUBLIC_DATASETS[0].columns]
    assert page["rows"][0][columns.index("reported_percentage")] == "33.333333333333"
    assert page["rows"][0][columns.index("calculated_percentage_rounded")] == "33.33"
    assert (
        service.page(token, "national", start=date(2026, 9, 2))["rows"]
        == page["rows"][:1]
    )
    assert (
        service.page(token, "national", end=date(2026, 9, 1))["rows"]
        == page["rows"][1:]
    )
    assert (
        service.page(token, "national", start=date(2026, 9, 1), end=date(2026, 9, 1))[
            "rows"
        ]
        == page["rows"][1:]
    )
    empty = service.page(token, "national", start=date(2026, 9, 3))
    assert (
        empty["rows"] == []
        and empty["has_more"] is False
        and empty["next_cursor"] is None
    )


def test_binary_identifier_ties_revisit_and_no_raw_graph_download(system, browsing):
    service, cache, _, _, runtime, client, _ = browsing
    token = system[2][Role.ANALYST]
    client.calls.clear()
    first = service.page(token, "facilities", size=3)
    visited, all_rows = [first], list(first["rows"])
    current = first
    while current["has_more"]:
        current = service.page(token, "facilities", cursor=current["next_cursor"])
        visited.append(current)
        all_rows.extend(current["rows"])
    assert [values[4] for values in all_rows] == sorted(
        ["001", "01", "1", "A", "Z", "a", "é", "😀"], key=lambda s: s.encode("utf-8")
    )
    assert service.page(token, "facilities", cursor=first["page_cursor"]) == first
    # One exact resource file, without manifest/metadata discovery.
    assert len([call for call in client.calls if call[0] == "get"]) == 1
    assert len(runtime.calls[0].files) == 1
    for file in runtime.calls[0].files:
        assert "source_json" in pq.read_schema(file.path).names or len(
            pq.read_schema(file.path).names
        ) > len(PUBLIC_DATASETS[1].columns)
    assert all(entry.pins == 1 for entry in cache._entries.values())


@pytest.mark.parametrize("size", [None, 500])
def test_default_and_max_page_sizes_and_503_row_keyset(system, browsing, size):
    service = browsing[0]
    token = system[2][Role.ADMIN]
    page = service.page(token, "generators", size=size)
    fixed = 100 if size is None else size
    assert page["page_size"] == fixed and len(page["rows"]) == fixed
    rows = list(page["rows"])
    while page["has_more"]:
        page = service.page(token, "generators", cursor=page["next_cursor"])
        assert page["page_size"] == fixed
        rows.extend(page["rows"])
    assert len(rows) == 503
    assert [values[-1] for values in rows] == [f"{value:04}" for value in range(503)]


def test_expiry_is_exact_fixed_and_cleanup_releases_pins(system, browsing):
    service, cache, sequences, clock, _, _, _ = browsing
    token = system[2][Role.VIEWER]
    page = service.page(token, "national", size=1)
    created = clock.now()
    assert page["expires_at"] == (created + timedelta(seconds=60)).isoformat().replace(
        "+00:00", "Z"
    )
    clock.value += timedelta(seconds=59)
    assert service.page(token, "national", cursor=page["page_cursor"]) == page
    clock.value += timedelta(seconds=1)
    sequences.cleanup()  # supervised cleanup does not require another request
    assert all(entry.pins == 0 for entry in cache._entries.values())
    with pytest.raises(PreviewUnavailableError):
        service.page(token, "national", cursor=page["page_cursor"])


def test_tampering_foreign_owner_and_changed_continuation_inputs(system, browsing):
    service = browsing[0]
    page = service.page(system[2][Role.VIEWER], "national", size=1)
    for cursor in (page["next_cursor"] + "x", page["next_cursor"][:-1], "not-a-cursor"):
        with pytest.raises(PreviewUnavailableError):
            service.page(system[2][Role.VIEWER], "national", cursor=cursor)
    with pytest.raises(PreviewUnavailableError):
        service.page(system[2][Role.ADMIN], "national", cursor=page["next_cursor"])
    with pytest.raises(InvalidRequestError):
        service.page(
            system[2][Role.VIEWER], "national", cursor=page["page_cursor"], size=1
        )


def test_role_change_and_logout_deny_before_continuation_execution(
    system, database, browsing
):
    service, _, _, _, runtime, _, _ = browsing
    token = system[2][Role.ANALYST]
    first = service.page(token, "facilities", size=1)
    calls = len(runtime.calls)
    with psycopg.connect(database) as connection:
        connection.execute(
            "UPDATE users SET role_code='viewer' WHERE id=%s",
            (system[3][Role.ANALYST].id,),
        )
    with pytest.raises(ForbiddenError):
        service.page(token, "facilities", cursor=first["next_cursor"])
    assert len(runtime.calls) == calls
    system[1]._access.logout(token)
    with pytest.raises(UnauthenticatedError):
        service.page(token, "national")


def test_old_generation_reads_during_new_publication_and_source_unavailable(
    system, database, browsing, tmp_path
):
    service, _, _, _, _, client, values = browsing
    token = system[2][Role.VIEWER]
    first = service.page(token, "national", size=1)
    previous = service.page(token, "national", cursor=first["next_cursor"])
    changed = values | {
        "national": [
            row("national", period="2026-09-01", outage="2"),
            row("national", period="2026-09-02", outage="2"),
        ]
    }
    result = execute(
        system, database, tmp_path / "new-refresh", changed, client, key="b" * 16
    )
    assert result.status.value == "succeeded", (result.failure, result.quality_json)
    assert service.page(token, "national", cursor=first["page_cursor"]) == first
    assert service.page(token, "national", cursor=first["next_cursor"]) == previous
    fresh = service.page(token, "national", size=1)
    assert fresh["generation_id"] != first["generation_id"]
    assert fresh["rows"][0][2] == "2.000000000000"
    # Browser has no source port at all: all reads are published-only.


def test_integrity_failure_and_busy_before_download(system, browsing):
    service, cache, _, _, _, client, _ = browsing
    token = system[2][Role.VIEWER]
    reservation = service._execution.reserve()
    client.calls.clear()
    try:
        with pytest.raises(AnalyticalBusyError):
            service.page(token, "national")
        assert client.calls == []
    finally:
        reservation.close()
    page = service.page(token, "national")
    file = next(iter(cache._entries.values())).files[0]
    path = Path(file.path)
    path.chmod(0o600)
    path.write_bytes(b"corrupted")
    with pytest.raises(DataUnavailableError):
        service.page(token, "national")
    with pytest.raises(DataUnavailableError):
        service.page(token, "national", cursor=page["page_cursor"])


@pytest.mark.parametrize("size", [0, 501, True, "100"])
def test_invalid_size_and_reversed_dates(system, browsing, size):
    with pytest.raises(InvalidRequestError):
        browsing[0].page(system[2][Role.VIEWER], "national", size=size)
    with pytest.raises(InvalidRequestError):
        browsing[0].page(
            system[2][Role.VIEWER],
            "national",
            start=date(2026, 9, 2),
            end=date(2026, 9, 1),
        )


def test_response_byte_prefix_never_skips_and_oversized_first_row(system, browsing):
    service = browsing[0]
    token = system[2][Role.ADMIN]
    reference = service.page(token, "generators", size=5)
    service._response_bytes = len(canonical_json(reference)) - 10
    page = service.page(token, "generators", size=5)
    assert 0 < len(page["rows"]) < 5 and page["has_more"]
    first_rows = page["rows"]
    following = service.page(token, "generators", cursor=page["next_cursor"])
    assert following["rows"][0][-1] == f"{len(first_rows):04}"
    service._response_bytes = 1
    with pytest.raises(AnalyticalResourceError):
        service.page(token, "national")


def test_absent_reviewed_runtime_and_reaping_capacity_are_fail_closed():
    with pytest.raises(RuntimeUnavailableError):
        VerifiedLauncher(EXECUTION).reserve()
    runtime = Mock()
    launcher = VerifiedLauncher(EXECUTION, runtime, evidence="test only")
    reservation = launcher.reserve()
    with pytest.raises(AnalyticalBusyError):
        launcher.reserve()
    runtime.terminate_and_reap.side_effect = OSError("test failed reaping")
    with pytest.raises(OSError):
        reservation.close()
    with pytest.raises(AnalyticalBusyError):
        launcher.reserve()
    runtime.terminate_and_reap.side_effect = None
    reservation.close()
    launcher.reserve().close()


def test_metadata_counts_bytes_and_active_expiry_cleanup():
    clock, inputs = Clock(), Mock()
    inputs.files = ()
    generation = Mock()
    store = BoundedPreviewSequences(clock, replace(METADATA, per_user=1), b"x" * 32)
    seq = store.create("a", PUBLIC_DATASETS[0], generation, None, None, 100, inputs)
    cursor = store.cursor(seq, None)
    with pytest.raises(PreviewCapacityError):
        store.create("a", PUBLIC_DATASETS[0], generation, None, None, 100, inputs)
    position = store.acquire(cursor, "a", PUBLIC_DATASETS[0])
    clock.value += timedelta(seconds=60)
    store.cleanup()
    inputs.close.assert_not_called()
    store.release(position.sequence)
    inputs.close.assert_not_called()
    store.release(seq)
    inputs.close.assert_called_once()
    with pytest.raises(PreviewUnavailableError):
        store.acquire(cursor, "a", PUBLIC_DATASETS[0])
    tiny = BoundedPreviewSequences(
        clock, replace(METADATA, metadata_bytes=1), b"x" * 32
    )
    with pytest.raises(PreviewCapacityError):
        tiny.create("a", PUBLIC_DATASETS[0], generation, None, None, 100, inputs)


def test_local_modeled_projection_and_controlled_worker_without_cloud_or_database(
    tmp_path,
):
    """Synthetic publication port; real Parquet and separate engine process."""
    rows = {
        grain: [row(grain, period=day) for day in ("2026-09-01", "2026-09-02")]
        for grain in ("national", "facility", "generator")
    }
    result, _ = connector.execute(tmp_path / "connector", rows)
    assert result.report.outcome == "candidate_verified"
    candidate = result.report.candidate
    store = connector.LocalParquetStore(tmp_path / "connector" / "objects", ARTIFACT)
    filenames = {
        "national": "national",
        "facility": "facilities",
        "generator": "generators",
    }
    descriptors = tuple(
        replace(
            ref,
            object=replace(
                ref.object,
                key=f"connector/generations/{candidate.generation_id}/{filenames[ref.grain]}.parquet",
            ),
        )
        for ref in candidate.resources
    )

    class Objects:
        def read(self, reference):
            return store.read(replace(reference, key=reference.sha256))

    generation = ResourcePublishedGeneration(
        candidate.generation_id,
        "synthetic-run",
        None,
        "v1",
        datetime.now(UTC),
        tuple(
            DatasetSummary(
                AnalyticalGrain(ref.grain),
                "v1",
                ref.row_count,
                date(2026, 9, 1),
                date(2026, 9, 2),
                ref.object.key,
                ref.object.sha256,
                ref.object.byte_count,
            )
            for ref in descriptors
        ),
    )
    cache = VerifiedResourceCache(tmp_path / "cache", Objects(), ARTIFACT, CACHE)
    runtime = ControlledRuntime()
    launcher = VerifiedLauncher(
        EXECUTION, runtime, evidence="controlled test fixture only"
    )
    access = Mock()
    access.authorize.return_value.principal.id = "synthetic-user"
    publications = Mock()
    publications.active_generation.return_value = generation
    clock = Clock()
    sequences = BoundedPreviewSequences(clock, METADATA, b"x" * 32)
    service = PreviewService(
        access,
        publications,
        cache,
        launcher,
        sequences,
        PreviewEncoding(ENCODING),
        response_bytes=1024**2,
    )
    for dataset in PUBLIC_DATASETS:
        first = service.page("synthetic-token", dataset.id, size=1)
        assert first["rows"][0][0] == "2026-09-02"
        second = service.page(
            "synthetic-token", dataset.id, cursor=first["next_cursor"]
        )
        assert second["rows"][0][0] == "2026-09-01" and not second["has_more"]
        assert (
            service.page("synthetic-token", dataset.id, cursor=first["page_cursor"])
            == first
        )
    sequences.close()
    assert all(entry.pins == 0 for entry in cache._entries.values())

    # Cached content cannot authenticate a changed publication identity.
    with pytest.raises(DataUnavailableError):
        cache.prepare(
            replace(generation, id="different-generation"), PUBLIC_DATASETS[0]
        )
    limited = VerifiedResourceCache(
        tmp_path / "limited-cache", Objects(), ARTIFACT, replace(CACHE, files=1)
    )
    pin = limited.prepare(generation, PUBLIC_DATASETS[0])
    with pytest.raises(AnalyticalResourceError):
        limited.prepare(generation, PUBLIC_DATASETS[1])
    assert all(Path(file.path).exists() for file in pin.files)
    pin.close()
    following = limited.prepare(generation, PUBLIC_DATASETS[1])
    assert all(not Path(file.path).exists() for file in pin.files)
    following.close()


def test_unreaped_worker_keeps_active_preview_pin_through_expiry():
    clock = Clock()
    inputs = Mock()
    inputs.files = ()
    cache = Mock()
    cache.prepare.return_value = inputs
    publications = Mock()
    access = Mock()
    access.authorize.return_value.principal.id = "user"
    sequences = BoundedPreviewSequences(clock, METADATA, b"x" * 32)
    runtime = Mock()
    runtime.preview.return_value = PreviewRows((), (), False)
    runtime.terminate_and_reap.side_effect = OSError("controlled failed reap")
    launcher = VerifiedLauncher(EXECUTION, runtime, evidence="test only")
    service = PreviewService(
        access,
        publications,
        cache,
        launcher,
        sequences,
        PreviewEncoding(ENCODING),
        response_bytes=1024**2,
    )
    with pytest.raises(OSError):
        service.page("test-token", "national")
    clock.value += timedelta(seconds=60)
    sequences.cleanup()
    inputs.close.assert_not_called()
    assert launcher.recovery.pending == 1
    launcher.recovery.reconcile()
    inputs.close.assert_not_called()
    with pytest.raises(AnalyticalBusyError):
        launcher.reserve()
    runtime.terminate_and_reap.side_effect = None
    launcher.recovery.reconcile()
    inputs.close.assert_called_once()
    assert launcher.recovery.pending == 0
    launcher.reserve().close()


def test_missing_runtime_denies_before_publication_or_preparation():
    access, publications, cache, sequences = Mock(), Mock(), Mock(), Mock()
    service = PreviewService(
        access,
        publications,
        cache,
        VerifiedLauncher(EXECUTION),
        sequences,
        PreviewEncoding(ENCODING),
        response_bytes=1024**2,
    )
    with pytest.raises(RuntimeUnavailableError):
        service.page("test-token", "national")
    publications.active_generation.assert_not_called()
    cache.prepare.assert_not_called()


@pytest.fixture
def portable_selection():
    """Real authorization/store/lifecycle; observed injected execution, no database.

    The port returns synthetic rows to exercise pagination, not facility equality.
    That query belongs to the real worker in phase 3.
    """
    from types import SimpleNamespace

    from outage_explorer.application.services.access import AccessService
    from outage_explorer.domain.access import SeededUser, Session

    clock = Clock()
    token = "a" * 43
    user = SeededUser("analyst", "test-issuer", "test-subject", "a@test", Role.ANALYST)
    sessions = Mock()
    sessions.resolve_session.return_value = Session(
        token, user, clock.now(), clock.now() + timedelta(hours=1)
    )
    security = Mock()
    security.digest.side_effect = lambda value: value
    access = AccessService(sessions, security, clock)
    generation = ResourcePublishedGeneration("old", "run", None, "v1", clock.now(), ())
    publications = Mock()
    publications.active_generation.return_value = generation
    inputs = Mock()
    pins = []

    def prepare(generation, dataset):
        pin = Mock()
        pin.files = ()
        pins.append(pin)
        return pin

    inputs.prepare.side_effect = prepare
    runtime = Mock()
    requests = []

    def preview(request, bounds, deadline):
        from decimal import Decimal

        requests.append(request)
        day = date(2026, 9, 2) if request.after is None else date(2026, 9, 1)
        values = {
            "period": day,
            "facility": request.facility or "001",
            "facility_name": "Synthetic",
            "generator": "G",
        }
        row = tuple(
            values.get(column.name, Decimal("1")) for column in request.dataset.columns
        )
        key = tuple(
            str(values[column.name])
            for column in request.dataset.columns
            if column.name in {"period", "facility", "generator"}
        )
        return PreviewRows((row,), (key,), request.after is None)

    runtime.preview.side_effect = preview
    launcher = VerifiedLauncher(EXECUTION, runtime, evidence="injected port only")
    sequences = BoundedPreviewSequences(clock, METADATA, b"x" * 32)
    service = PreviewService(
        access,
        publications,
        inputs,
        launcher,
        sequences,
        PreviewEncoding(ENCODING),
        response_bytes=1024**2,
    )
    yield SimpleNamespace(
        service=service,
        token=token,
        sessions=sessions,
        clock=clock,
        publications=publications,
        inputs=inputs,
        pins=pins,
        runtime=runtime,
        requests=requests,
        launcher=launcher,
        sequences=sequences,
    )
    runtime.terminate_and_reap.side_effect = None
    launcher.recovery.reconcile()
    sequences.close()


@pytest.mark.parametrize("dataset", ["facilities", "generators"])
@pytest.mark.parametrize("facility", ["001", "é", "A' OR 1=1 --"])
def test_portable_facility_selection_continuation_revisit_and_snapshot(
    portable_selection, dataset, facility
):
    state = portable_selection
    start, end = date(2026, 9, 1), date(2026, 9, 2)
    first = state.service.page(
        state.token, dataset, facility=facility, start=start, end=end, size=1
    )
    state.publications.active_generation.return_value = replace(
        state.publications.active_generation.return_value, id="new"
    )
    second = state.service.page(state.token, dataset, cursor=first["next_cursor"])
    assert (
        state.service.page(state.token, dataset, cursor=first["page_cursor"]) == first
    )
    assert first["generation_id"] == second["generation_id"] == "old"
    assert [
        (request.facility, request.start, request.end, request.size)
        for request in state.requests
    ] == [(facility, start, end, 1)] * 3
    assert (
        state.requests[1].after
        == ("2026-09-02", facility, "G")[: 3 if dataset == "generators" else 2]
    )
    state.inputs.prepare.assert_called_once()
    state.pins[0].close.assert_not_called()
    fresh = state.service.page(state.token, dataset, facility="other")
    assert fresh["generation_id"] == "new"
    assert state.requests[-1].facility == "other"


@pytest.mark.parametrize(
    "facility", ["", " 001", "001 ", "\x00", "\x85", "\ud800", "é" * 129, 1, ["001"]]
)
def test_portable_facility_invalid_direct_calls_before_resources(
    portable_selection, facility
):
    state = portable_selection
    with pytest.raises(InvalidRequestError):
        state.service.page(state.token, "facilities", facility=facility)
    state.inputs.prepare.assert_not_called()
    state.runtime.preview.assert_not_called()
    state.publications.active_generation.assert_not_called()


def test_portable_facility_national_and_cursor_mixtures(portable_selection):
    state = portable_selection
    with pytest.raises(InvalidRequestError):
        state.service.page(state.token, "national", facility="001")
    first = state.service.page(state.token, "facilities", facility="001")
    calls = len(state.requests)
    for facility in ("001", "", "different"):
        with pytest.raises(InvalidRequestError):
            state.service.page(
                state.token,
                "facilities",
                cursor=first["page_cursor"],
                facility=facility,
            )
    assert len(state.requests) == calls


@pytest.mark.parametrize(
    "denial", ["viewer", "absent", "expired", "revoked", "foreign", "role-change"]
)
def test_portable_facility_authorization_before_inputs_and_execution(
    portable_selection, denial
):
    state = portable_selection
    cursor = None
    if denial in {"foreign", "role-change"}:
        cursor = state.service.page(state.token, "facilities", facility="001")[
            "page_cursor"
        ]
    state.inputs.prepare.reset_mock()
    state.runtime.preview.reset_mock()
    state.publications.active_generation.reset_mock()
    session = state.sessions.resolve_session.return_value
    if denial in {"viewer", "role-change"}:
        state.sessions.resolve_session.return_value = replace(
            session, user=replace(session.user, role=Role.VIEWER)
        )
        error = ForbiddenError
    elif denial == "foreign":
        state.sessions.resolve_session.return_value = replace(
            session, user=replace(session.user, id="other")
        )
        error = PreviewUnavailableError
    else:
        if denial == "expired":
            state.clock.value = session.expires_at
        else:
            state.sessions.resolve_session.return_value = None
        error = UnauthenticatedError
    with pytest.raises(error):
        state.service.page(
            "" if denial == "absent" else state.token,
            "facilities",
            cursor=cursor,
            facility=None if cursor else "",
        )
    state.inputs.prepare.assert_not_called()
    state.runtime.preview.assert_not_called()
    state.publications.active_generation.assert_not_called()


def test_portable_facility_fixed_expiry_and_pin_cleanup(portable_selection):
    state = portable_selection
    first = state.service.page(state.token, "generators", facility="001", size=1)
    state.clock.value += timedelta(seconds=59)
    assert (
        state.service.page(state.token, "generators", cursor=first["page_cursor"])
        == first
    )
    state.clock.value += timedelta(seconds=1)
    state.sequences.cleanup()
    state.pins[0].close.assert_called_once()
    calls = len(state.requests)
    with pytest.raises(PreviewUnavailableError):
        state.service.page(state.token, "generators", cursor=first["page_cursor"])
    assert len(state.requests) == calls


def test_portable_facility_utf8_metadata_capacity_and_rollback(portable_selection):
    state = portable_selection
    dataset = PUBLIC_DATASETS[1]
    generation = state.publications.active_generation.return_value
    pin = Mock(files=())
    # Observe the no-filter charge, then allow exactly two additional bytes.
    probe = BoundedPreviewSequences(state.clock, METADATA, b"x" * 32)
    unfiltered = probe.create("analyst", dataset, generation, None, None, 100, pin)
    baseline = probe._bytes
    probe.discard(unfiltered)
    probe.release(unfiltered)
    pin.close.reset_mock()
    bounds = replace(METADATA, metadata_bytes=baseline + 2)
    state.service._sequences = BoundedPreviewSequences(state.clock, bounds, b"x" * 32)
    with pytest.raises(PreviewCapacityError):
        state.service.page(state.token, "facilities", facility="éé")
    state.pins[0].close.assert_called_once()
    state.runtime.preview.assert_not_called()
    # Failed admission consumed no capacity. A two-byte selection fits exactly.
    store = state.service._sequences
    sequence = store.create(
        "analyst", dataset, generation, None, None, 100, pin, facility="é"
    )
    assert sequence.facility == "é"
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        sequence.facility = "other"
    store.discard(sequence)
    store.release(sequence)
    pin.close.assert_called_once()


def test_portable_facility_unreaped_worker_retains_pin_until_reconciliation(
    portable_selection,
):
    state = portable_selection
    state.runtime.terminate_and_reap.side_effect = OSError("controlled failed reap")
    with pytest.raises(OSError):
        state.service.page(state.token, "facilities", facility="001")
    state.clock.value += timedelta(seconds=60)
    state.sequences.cleanup()
    state.pins[0].close.assert_not_called()
    with pytest.raises(AnalyticalBusyError):
        state.launcher.reserve()
    state.runtime.terminate_and_reap.side_effect = None
    state.launcher.recovery.reconcile()
    state.pins[0].close.assert_called_once()


def test_portable_facility_lost_store_rejects_cursor_before_execution(
    portable_selection,
):
    state = portable_selection
    first = state.service.page(state.token, "facilities", facility="001")
    state.sequences.close()
    state.pins[0].close.assert_called_once()
    state.service._sequences = BoundedPreviewSequences(state.clock, METADATA, b"x" * 32)
    calls = len(state.requests)
    with pytest.raises(PreviewUnavailableError):
        state.service.page(state.token, "facilities", cursor=first["page_cursor"])
    assert len(state.requests) == calls
    assert state.inputs.prepare.call_count == 1


def test_portable_facility_forward_sequences_preserves_selection(portable_selection):
    from outage_explorer.infrastructure.worker_runtime.supervisor import (
        ForwardSequences,
    )

    state = portable_selection
    supervisor = Mock()
    supervisor.ready.return_value.sequences = state.sequences
    sequences = ForwardSequences(supervisor)
    generation = state.publications.active_generation.return_value
    pin = Mock(files=())
    sequence = sequences.create(
        "analyst", PUBLIC_DATASETS[1], generation, None, None, 100, pin, facility="001"
    )
    assert sequence.facility == "001"
    cursor = sequences.cursor(sequence, None)
    assert (
        sequences.acquire(cursor, "analyst", PUBLIC_DATASETS[1]).sequence.facility
        == "001"
    )
    state.sequences.release(sequence)
    state.sequences.release(sequence)
