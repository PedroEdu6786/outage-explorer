"""Native Linux candidate parser controls; no API, Docker, AWS or measurements."""

import os
import shutil
import subprocess
import sys
from threading import Event, Thread

import pytest

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.sql_inspection import SqlRejected
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import (
    InspectionBounds,
    SubprocessSqlInspector,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("prlimit") is None,
    reason="Native Linux prlimit required",
)


@pytest.fixture
def parser():
    adapter = SubprocessSqlInspector(
        InspectionBounds(
            wall_seconds=4,
            cpu_seconds=1,
            memory_bytes=256 * 1024**2,
            termination_seconds=1,
            stderr_bytes=1024,
            max_sql_bytes=65536,
            max_nodes=10000,
            max_depth=64,
        ),
        python=sys.executable,
        prlimit=shutil.which("prlimit"),
    )
    yield adapter
    adapter.close()


def replace_child(monkeypatch, code):
    launch = subprocess.Popen

    def controlled(arguments, **kwargs):
        assert arguments[-2:] == (
            "-m",
            "outage_explorer.infrastructure.sql_validation.parser_process",
        )
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
        assert (
            kwargs["cwd"] == "/" and kwargs["close_fds"] and kwargs["start_new_session"]
        )
        return launch((*arguments[:-2], "-c", code), **kwargs)

    monkeypatch.setattr(subprocess, "Popen", controlled)


@pytest.mark.parametrize(
    "sql,scope",
    [
        ("SELECT 1", set()),
        ("SELECT * FROM national", {"national"}),
        (
            "WITH unused AS (SELECT * FROM generators) SELECT * FROM national",
            {"national", "generator"},
        ),
    ],
)
def test_real_limited_child_scope_and_reap(parser, sql, scope):
    inspected = parser.inspect(sql)
    assert inspected.sql == sql and inspected.grains == scope
    assert inspected.reference_free == (not scope)
    assert parser._process is None and not parser._slot.locked()


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_parquet('/private/secret')",
        "DELETE FROM national",
        "SELECT 1; SELECT 2",
    ],
)
def test_real_parser_safe_rejection(parser, sql):
    with pytest.raises(SqlRejected):
        parser.inspect(sql)
    assert parser._process is None and not parser._slot.locked()


@pytest.mark.parametrize(
    "code,error",
    [
        ("import time; time.sleep(20)", AnalyticalTimeoutError),
        ("while True: pass", RuntimeUnavailableError),
        (
            'import sys; sys.stdout.buffer.write(b"x"*2048); sys.stdout.flush()',
            AnalyticalResourceError,
        ),
        (
            'import sys; sys.stderr.buffer.write(b"x"*2048); sys.stderr.flush()',
            AnalyticalResourceError,
        ),
        (
            'import sys; sys.stderr.write("private diagnostic"); sys.exit(2)',
            RuntimeUnavailableError,
        ),
        ("memory = bytearray(1024**3)", RuntimeUnavailableError),
        ('print("{}")', RuntimeUnavailableError),
    ],
)
def test_native_limits_and_safe_failure(parser, monkeypatch, code, error):
    replace_child(monkeypatch, code)
    with pytest.raises(error) as failure:
        parser.inspect("SELECT 1")
    assert "private" not in str(failure.value)
    assert parser._process is None and not parser._slot.locked()


def test_native_minimal_environment_and_closed_descriptors(
    parser, monkeypatch, tmp_path
):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-parser-denial-canary")
    with (tmp_path / "private-canary").open("wb") as inherited:
        os.set_inheritable(inherited.fileno(), True)
        code = 'import os,json; assert "AWS_SECRET_ACCESS_KEY" not in os.environ\n'
        code += f"try:\n os.fstat({inherited.fileno()})\nexcept OSError:\n pass\nelse:\n raise AssertionError\n"
        code += 'print(json.dumps(dict(version=1,status="ok",grains=[])))'
        replace_child(monkeypatch, code)
        assert parser.inspect("SELECT 1").reference_free


def test_native_close_cancels_and_reaps(parser, monkeypatch):
    entered = Event()
    launch = subprocess.Popen

    def controlled(arguments, **kwargs):
        process = launch(
            (*arguments[:-2], "-c", "import time; time.sleep(20)"), **kwargs
        )
        entered.set()
        return process

    monkeypatch.setattr(subprocess, "Popen", controlled)
    failures = []

    def inspect():
        try:
            parser.inspect("SELECT 1")
        except Exception as error:
            failures.append(error)

    thread = Thread(target=inspect)
    thread.start()
    assert entered.wait(2)
    try:
        with pytest.raises(RuntimeUnavailableError, match="shutdown pending"):
            parser.close()
    finally:
        thread.join(3)
    assert not thread.is_alive()
    assert len(failures) == 1 and isinstance(failures[0], AnalyticalTimeoutError)
    parser.close()
    assert parser._process is None and not parser._slot.locked()
