"""Parser process control/protocol checks; candidate limits are not runtime budgets."""

import json
import subprocess
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
    InspectionBounds,
    SubprocessSqlInspector,
    UnavailableSqlInspector,
)
from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    decode_scope,
    inspect_request,
)


def bounds(**changes):
    return InspectionBounds(
        **(
            dict(
                wall_seconds=2,
                cpu_seconds=1,
                memory_bytes=256 * 1024**2,
                termination_seconds=1,
                stderr_bytes=1024,
                max_sql_bytes=65536,
                max_nodes=10000,
                max_depth=64,
            )
            | changes
        )
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("wall_seconds", float("inf")),
        ("wall_seconds", True),
        ("termination_seconds", 0),
        ("cpu_seconds", 1.5),
        ("cpu_seconds", True),
        ("memory_bytes", 0),
        ("stderr_bytes", -1),
        ("max_sql_bytes", 65537),
        ("max_nodes", 10001),
        ("max_depth", 65),
    ],
)
def test_reject_invalid_explicit_bounds(field, value):
    with pytest.raises(ValueError):
        bounds(**{field: value})


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b'{"version":true,"status":"ok","grains":[]}',
        b'{"version":2,"status":"ok","grains":[]}',
        b'{"version":1,"status":"ok","grains":["national","national"]}',
        b'{"version":1,"status":"ok","grains":["private"]}',
        b'{"version":1,"status":"ok","grains":[[]]}',
        b'{"version":1,"status":"ok","grains":[],"sql":"secret"}',
        b'{"version":1,"status":"ok","grains":[],"version":1}',
        b'{"version":1,"status":"rejected","code":"secret"}',
        b"x" * 1025,
    ],
)
def test_reject_invalid_child_scope(raw):
    with pytest.raises(ValueError):
        decode_scope(raw, "SELECT 1")


@pytest.mark.parametrize(
    "sql,grains",
    [
        ("SELECT 1", []),
        ("SELECT * FROM national", ["national"]),
        (
            "WITH unused AS (SELECT * FROM generators) SELECT * FROM national",
            ["generator", "national"],
        ),
    ],
)
def test_child_scope_preserves_original_sql(sql, grains):
    raw = json.dumps(
        dict(version=1, sql=sql, max_sql_bytes=65536, max_nodes=10000, max_depth=64)
    ).encode()
    response = inspect_request(raw)
    assert sql.encode() not in response
    inspected = decode_scope(response, sql)
    assert inspected.sql == sql and inspected.grains == frozenset(grains)
    assert inspected.reference_free == (not grains)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b'{"version":1,"sql":"x","max_sql_bytes":true,"max_nodes":1,"max_depth":1}',
        b"x" * 400000,
    ],
)
def test_malformed_child_request_has_safe_rejection(raw):
    assert json.loads(inspect_request(raw)) == dict(
        version=1, status="rejected", code="invalid_sql"
    )


def test_parser_denial_is_safe():
    raw = json.dumps(
        dict(
            version=1,
            sql="SELECT * FROM read_parquet('/private/secret')",
            max_sql_bytes=65536,
            max_nodes=10000,
            max_depth=64,
        )
    ).encode()
    with pytest.raises(SqlRejected, match="SQL is not supported"):
        decode_scope(inspect_request(raw), "original")


@pytest.fixture
def inspector(monkeypatch):
    monkeypatch.setattr(
        "outage_explorer.infrastructure.sql_validation.subprocess_inspection.sys.platform",
        "linux",
    )
    return SubprocessSqlInspector(
        bounds(), python="/trusted/python", prlimit="/usr/bin/prlimit"
    )


def test_construction_and_unavailable_adapter_do_not_launch(monkeypatch):
    launch = Mock(side_effect=AssertionError)
    monkeypatch.setattr(subprocess, "Popen", launch)
    adapter = SubprocessSqlInspector(
        bounds(), python="/trusted/python", prlimit="/usr/bin/prlimit"
    )
    adapter.close()
    adapter.close()
    with pytest.raises(RuntimeUnavailableError):
        UnavailableSqlInspector().inspect("SELECT 1")
    launch.assert_not_called()


def test_invalid_input_and_launch_failure_release_slot(inspector, monkeypatch):
    with pytest.raises(SqlRejected):
        inspector.inspect("\ud800")
    monkeypatch.setattr(subprocess, "Popen", Mock(side_effect=OSError("private path")))
    for _ in range(2):
        with pytest.raises(
            RuntimeUnavailableError, match="^Bounded SQL inspection unavailable$"
        ):
            inspector.inspect("SELECT 1")
    assert not inspector._slot.locked()


def test_admission_is_bounded_and_close_interrupts(inspector, monkeypatch):
    entered, finish = Event(), Event()

    def run(data, deadline):
        entered.set()
        assert finish.wait(2)
        assert inspector._cancel.is_set()
        return b'{"version":1,"status":"ok","grains":[]}'

    monkeypatch.setattr(inspector, "_run", run)
    thread = Thread(target=lambda: inspector.inspect("SELECT 1"))
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(AnalyticalBusyError):
            inspector.inspect("SELECT 2")
        with pytest.raises(RuntimeUnavailableError, match="shutdown pending"):
            inspector.close()
    finally:
        finish.set()
        thread.join(2)
    assert not thread.is_alive()
    inspector.close()
    with pytest.raises(RuntimeUnavailableError):
        inspector.inspect("SELECT 3")


def test_unconfirmed_reap_keeps_capacity_until_explicit_close(inspector, monkeypatch):
    process = Mock(pid=123456)
    process.wait.side_effect = subprocess.TimeoutExpired("hidden", 1)

    def run(data, deadline):
        inspector._process = process
        return b'{"version":1,"status":"ok","grains":[]}'

    monkeypatch.setattr(inspector, "_run", run)
    kill = Mock()
    monkeypatch.setattr("os.killpg", kill)
    with pytest.raises(RuntimeUnavailableError, match="death unconfirmed"):
        inspector.inspect("SELECT 1")
    assert inspector._slot.locked() and inspector._process is process
    with pytest.raises(RuntimeUnavailableError):
        inspector.inspect("SELECT 2")
    process.wait.side_effect = None
    kill.side_effect = [None, ProcessLookupError()]
    inspector.close()
    assert inspector._process is None and not inspector._slot.locked()


def test_authentication_and_scope_authorization_precede_inputs():
    from outage_explorer.application.errors import ForbiddenError, UnauthenticatedError
    from outage_explorer.application.services.queries import QueryService

    access, parser, publication, inputs, execution, results = (Mock() for _ in range(6))
    service = QueryService(access, parser, publication, inputs, execution, results)
    access.resolve.side_effect = UnauthenticatedError()
    with pytest.raises(UnauthenticatedError):
        service.execute("private-session", "SELECT 1")
    parser.inspect.assert_not_called()
    access.resolve.side_effect = None
    parser.inspect.return_value = decode_scope(
        b'{"version":1,"status":"ok","grains":["generator"]}',
        "SELECT * FROM generators",
    )
    access.authorize.side_effect = ForbiddenError()
    with pytest.raises(ForbiddenError):
        service.execute("private-session", "SELECT * FROM generators")
    publication.active_generation.assert_not_called()
    inputs.prepare.assert_not_called()
    execution.reserve.assert_not_called()
    results.reserve.assert_not_called()


def test_bootstrap_without_explicit_inspector_never_parses(monkeypatch):
    from outage_explorer.bootstrap import build_data_services
    from outage_explorer.infrastructure.sql_validation.inspection import (
        DuckdbSqlInspector,
    )

    parse = Mock(side_effect=AssertionError("API parsed SQL"))
    monkeypatch.setattr(DuckdbSqlInspector, "inspect", parse)
    access, store, security = Mock(), Mock(), Mock()
    services = build_data_services(
        access,
        store,
        security,
        {
            "OUTAGE_REFRESH_START_DATE": "2026-04-02",
            "OUTAGE_REFRESH_END_DATE": "2026-10-01",
        },
    )
    with pytest.raises(
        RuntimeUnavailableError, match="Bounded SQL inspection unavailable"
    ):
        services.queries.execute("session", "SELECT 1")
    parse.assert_not_called()
    store.active_generation.assert_not_called()
