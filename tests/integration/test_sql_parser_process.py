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
def parser(tmp_path):
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
        setpriv=shutil.which("setpriv"),
        ownership_root=tmp_path / "parser",
    )
    adapter.start()
    yield adapter
    adapter.close()


def replace_child(monkeypatch, code):
    launch = subprocess.Popen

    def controlled(arguments, **kwargs):
        assert arguments[-4:-2] == (
            "-m",
            "outage_explorer.infrastructure.sql_validation.parser_process",
        )
        assert kwargs["env"] == {"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"}
        assert (
            kwargs["cwd"] == "/" and kwargs["close_fds"] and kwargs["start_new_session"]
        )
        return launch((*arguments[:-4], "-c", code, *arguments[-2:]), **kwargs)

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
            (*arguments[:-4], "-c", "import time; time.sleep(20)", *arguments[-2:]),
            **kwargs,
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


def test_native_child_retains_ownership_until_confirmed_exit(parser):
    from outage_explorer.infrastructure.sql_validation.ownership import ParserOwnership

    lease = parser._ownership
    child = subprocess.Popen(
        (sys.executable, "-I", "-c", "import time; time.sleep(30)"),
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        pass_fds=(lease.fd,),
        start_new_session=True,
    )
    replacement = ParserOwnership(lease.root)
    try:
        lease.close()
        with pytest.raises(RuntimeUnavailableError, match="ownership unavailable"):
            replacement.open()
    finally:
        child.kill()
        child.wait(timeout=2)
    replacement.open()
    replacement.close()


def test_native_parent_loss_and_replacement_owner(parser):
    import selectors

    root = parser._ownership.root.parent / "restart-parser"
    # Fixed test child stalls, allowing a real controlling process to be killed.
    # No API server, sessions, analytical data or cloud configuration is involved.
    script = f"""
import subprocess,sys
from pathlib import Path
from outage_explorer.infrastructure.sql_validation.subprocess_inspection import InspectionBounds,SubprocessSqlInspector
adapter=SubprocessSqlInspector(InspectionBounds(4,1,268435456,1,1024,65536,10000,64),python=sys.executable,prlimit="/usr/bin/prlimit",setpriv="/usr/bin/setpriv",ownership_root=Path({str(root)!r}))
adapter.start()
launch=subprocess.Popen
def controlled(arguments,**kwargs):
    child=launch((*arguments[:-4],"-c","import os,sys,time; sys.exit(1) if os.getppid()!=int(sys.argv[1]) else time.sleep(30)",*arguments[-2:]),**kwargs)
    print(child.pid,flush=True)
    return child
subprocess.Popen=controlled
adapter.inspect("SELECT 1")
"""
    parent = subprocess.Popen(
        (sys.executable, "-I", "-c", script),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        start_new_session=True,
    )
    replacement = SubprocessSqlInspector(
        parser.bounds,
        python=sys.executable,
        prlimit=parser.prlimit,
        setpriv=parser.setpriv,
        ownership_root=root,
    )
    childfd = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(parent.stdout, selectors.EVENT_READ)
            assert selector.select(3)
            raw = os.read(parent.stdout.fileno(), 64)
        assert raw.strip().isdigit()
        child_pid = int(raw)
        childfd = os.pidfd_open(child_pid)
        with pytest.raises(RuntimeUnavailableError, match="ownership unavailable"):
            replacement.start()
        parent.kill()
        parent.wait(timeout=2)
        with selectors.DefaultSelector() as selector:
            selector.register(childfd, selectors.EVENT_READ)
            assert selector.select(3), "Parent-loss parser did not exit"
        replacement.start()
        assert replacement.inspect("SELECT 1").reference_free
        replacement.close()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)
        if childfd is not None:
            os.close(childfd)
        parent.stdout.close()
        replacement.close()


def test_native_wrong_parent_rejected_before_sql(parser, monkeypatch):
    launch = subprocess.Popen

    def controlled(arguments, **kwargs):
        return launch((*arguments[:-2], "1", arguments[-1]), **kwargs)

    monkeypatch.setattr(subprocess, "Popen", controlled)
    with pytest.raises(RuntimeUnavailableError, match="Bounded SQL inspection failed"):
        parser.inspect("SELECT 1")
    assert parser._process is None and not parser._slot.locked()
