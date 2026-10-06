"""Controlled Docker responses and real bounded host-control subprocesses only."""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
from unittest.mock import Mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.execution import QueryRead
from outage_explorer.domain.datasets import Column, ValueType
from outage_explorer.infrastructure.query_results.encoding import retain_result
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.docker import (
    BoundedDockerControl,
    ControlResult,
    DockerRuntime,
)
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger
from tests.integration.test_analytical_input_staging import (  # noqa: F401
    approved,
    profile,
)

ID = "b" * 64
OWNER = "c" * 32

DOCUMENT = retain_result(
    (Column("n", ValueType("integer")),),
    [],
    RuntimeProfile(
        "sha256:" + "a" * 64, "unix:///tmp/docker.sock", "test", "test", "test"
    ).encoding_bounds,
).document
RESPONSE = b'{"version":1,"operation":"query","result":' + DOCUMENT + b"}"


class Control:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.running = False
        self.oom = False
        self.exit = 0
        self.response = RESPONSE

    def run(self, arguments, **kwargs):
        self.calls.append((arguments, kwargs))
        operation = arguments[0]
        if self.fail == operation:
            raise RuntimeUnavailableError("controlled outage")
        if operation == "create":
            return ControlResult(0, ID.encode(), b"")
        if operation == "inspect":
            value = {
                "Id": ID,
                "Owner": OWNER,
                "State": {
                    "Running": self.running,
                    "Restarting": False,
                    "OOMKilled": self.oom,
                    "ExitCode": self.exit,
                },
            }
            return ControlResult(0, json.dumps(value).encode(), b"")
        if operation == "start":
            return ControlResult(self.exit, self.response, b"")
        if operation == "container":
            return ControlResult(0, ID.encode(), b"")
        if operation == "kill":
            self.running = False
        return ControlResult(0, b"0", b"")


@pytest.fixture
def runtime(profile, tmp_path):  # noqa: F811
    ledger = OwnershipLedger(tmp_path / "ownership", OWNER)
    ledger.open()
    control = Control()
    runtime = DockerRuntime(profile, control, ledger)
    yield runtime, control, ledger
    ledger.close()


def test_success_exact_canonical_result_and_isolation_arguments(runtime):
    adapter, control, ledger = runtime
    result = adapter.query(
        QueryRead("SELECT 42", ()), adapter.profile.execution_bounds, monotonic() + 5
    )
    assert result.document == DOCUMENT
    arguments = control.calls[0][0]
    for option in (
        "--read-only",
        "--interactive",
        "--mount" if False else "--network",
        "--cap-drop",
        "--security-opt",
        "--pids-limit",
        "--memory-swap",
        "--log-driver",
    ):
        assert option in arguments
    assert arguments[-1] == adapter.profile.image_id
    assert (
        "--env" not in arguments
        and "--volume" not in arguments
        and "--tty" not in arguments
    )
    adapter.terminate_and_reap()
    assert ledger.read() is None
    assert [args[0] for args, _ in control.calls][-4:] == [
        "inspect",
        "wait",
        "inspect",
        "rm",
    ]
    assert not list(Path(adapter.profile.staging_root).iterdir())


@pytest.mark.parametrize(
    "failure", ["create", "start", "inspect", "kill", "wait", "rm"]
)
def test_uncertain_control_retains_capacity_staging_and_explicit_leases(
    runtime, failure
):
    adapter, control, ledger = runtime
    launcher = VerifiedLauncher(
        adapter.profile.execution_bounds, adapter, evidence="controlled only"
    )
    reservation = launcher.reserve()
    if failure in {"create", "start", "inspect"}:
        control.fail = failure
        with pytest.raises(RuntimeUnavailableError):
            reservation.query(QueryRead("SELECT 42", ()))
    else:
        reservation.query(QueryRead("SELECT 42", ()))
        control.fail = failure
        control.running = failure == "kill"
    if failure in {"create", "start"}:
        control.fail = "inspect"
    lease = Mock()
    with pytest.raises(RuntimeUnavailableError):
        reservation.close()
    reservation.handoff((lease,))
    with pytest.raises(AnalyticalBusyError):
        launcher.reserve()
    assert ledger.read() is not None and list(
        Path(adapter.profile.staging_root).iterdir()
    )
    launcher.recovery.reconcile()
    lease.close.assert_not_called()
    control.fail = None
    launcher.recovery.reconcile()
    lease.close.assert_called_once()
    assert launcher.recovery.pending == 0 and ledger.read() is None
    launcher.reserve().close()


@pytest.mark.parametrize(
    "fault,error",
    [
        ("oom", AnalyticalResourceError),
        ("crash", RuntimeUnavailableError),
        ("protocol", RuntimeUnavailableError),
    ],
)
def test_worker_failure_safe_mapping_and_cleanup(runtime, fault, error):
    adapter, control, ledger = runtime
    if fault == "oom":
        control.oom = True
    elif fault == "crash":
        control.exit, control.response = 137, b""
    else:
        control.response = b"private diagnostics"
    with pytest.raises(error):
        adapter.query(
            QueryRead("SELECT 42", ()),
            adapter.profile.execution_bounds,
            monotonic() + 5,
        )
    adapter.terminate_and_reap()
    assert ledger.read() is None


def test_dead_but_remove_failed_never_releases_files(runtime):
    adapter, control, ledger = runtime
    adapter.query(
        QueryRead("SELECT 42", ()), adapter.profile.execution_bounds, monotonic() + 5
    )
    control.fail = "rm"
    with pytest.raises(RuntimeUnavailableError):
        adapter.terminate_and_reap()
    assert ledger.read() and adapter._staging is not None
    control.fail = None
    adapter.terminate_and_reap()
    assert ledger.read() is None


def test_quota_disk_not_silently_substituted(runtime):
    adapter, control, _ = runtime
    adapter.profile = replace(adapter.profile, temporary_backend="quota-disk")
    with pytest.raises(RuntimeUnavailableError):
        adapter.query(
            QueryRead("SELECT 42", ()),
            adapter.profile.execution_bounds,
            monotonic() + 5,
        )
    assert all(arguments[0] == "info" for arguments, _ in control.calls)
    adapter.terminate_and_reap()


@pytest.mark.parametrize(
    "mode,error",
    [
        ("stdout", AnalyticalResourceError),
        ("stderr", AnalyticalResourceError),
        ("sleep", AnalyticalTimeoutError),
        ("stdin", AnalyticalTimeoutError),
        ("child", AnalyticalTimeoutError),
    ],
)
def test_control_independent_stream_and_deadline_bounds(tmp_path, mode, error):
    executable = tmp_path / "fake-docker"
    executable.write_text(
        "#!"
        + sys.executable
        + '\nimport os, sys, time\nmode=sys.argv[-1]\nif mode == "stdout": os.write(1,b"x"*10000)\nif mode == "stderr": os.write(2,b"x"*10000)\nif mode == "child":\n if os.fork() == 0: time.sleep(10)\n else: sys.exit(0)\nif mode in ("sleep","stdin"): time.sleep(10)\n'
    )
    executable.chmod(0o700)
    control = BoundedDockerControl("unix:///tmp/test.sock", str(executable))
    started = monotonic()
    with pytest.raises(error):
        control.run(
            (mode,),
            data=b"x" * 100000 if mode == "stdin" else b"",
            deadline=started + 2,
            stdout_bytes=100,
            stderr_bytes=100,
        )
    assert monotonic() - started < 4


def test_control_cancellation_missing_executable_and_concurrent_io(tmp_path):
    executable = tmp_path / "fake-docker"
    executable.write_text(
        "#!"
        + sys.executable
        + '\nimport os, sys\nos.write(2,b"err")\nos.write(1,sys.stdin.buffer.read())\n'
    )
    executable.chmod(0o700)
    control = BoundedDockerControl("unix:///tmp/test.sock", str(executable))
    result = control.run(
        ("echo",),
        data=b"input",
        deadline=monotonic() + 2,
        stdout_bytes=10,
        stderr_bytes=10,
    )
    assert result.stdout == b"input" and result.stderr == b"err"
    event = Event()
    event.set()
    with pytest.raises(AnalyticalTimeoutError):
        control.run(
            ("echo",),
            data=b"input",
            deadline=monotonic() + 2,
            stdout_bytes=10,
            stderr_bytes=10,
            cancel=event,
        )
    with pytest.raises(RuntimeUnavailableError):
        BoundedDockerControl("unix:///tmp/test.sock", "/missing/docker").run(
            (), data=b"", deadline=monotonic() + 2, stdout_bytes=10, stderr_bytes=10
        )


def test_owner_lock_and_corrupt_bounded_ledger(tmp_path):
    first = OwnershipLedger(tmp_path / "ownership", OWNER)
    second = OwnershipLedger(tmp_path / "ownership", "d" * 32)
    with pytest.raises(RuntimeUnavailableError):
        first.read()
    first.open()
    try:
        with pytest.raises(RuntimeUnavailableError):
            second.open()
        first.intend("/private/staging")
        with pytest.raises(RuntimeUnavailableError):
            first.intend("/other")
        (first.root / "worker.json").write_bytes(b"x" * 8193)
        with pytest.raises(RuntimeUnavailableError):
            first.read()
    finally:
        first.close()


def test_recover_owned_accepts_sealed_private_staging_directory(runtime):
    adapter, control, ledger = runtime
    staging = Path(adapter.profile.staging_root) / "execution-orphan"
    staging.mkdir(mode=0o555)
    ledger.intend(str(staging), preparing=True)
    ledger.close()

    recovered_ledger = OwnershipLedger(ledger.root, "d" * 32)
    recovered_ledger.open()
    recovering = DockerRuntime(adapter.profile, control, recovered_ledger)
    try:
        recovering.recover_owned()
        assert recovered_ledger.read() is None
        assert not staging.exists()
    finally:
        recovered_ledger.close()


def test_only_exact_authorized_digest_files_bound_readonly(runtime, approved):  # noqa: F811
    from outage_explorer.domain.datasets import PUBLIC_DATASETS

    adapter, control, _ = runtime
    second_path = Path(approved.path).with_name("second.parquet")
    pq.write_table(pa.table({"n": [3]}), second_path)
    payload = second_path.read_bytes()
    second = ApprovedFile(
        str(second_path), hashlib.sha256(payload).hexdigest(), len(payload), 1
    )
    request = QueryRead(
        "SELECT * FROM national",
        ((PUBLIC_DATASETS[0], (approved, second)),),
    )
    adapter.query(request, adapter.profile.execution_bounds, monotonic() + 5)
    arguments = control.calls[0][0]
    mount = arguments[arguments.index("--mount") + 1]
    assert mount == (
        f"type=bind,src={adapter._staging.directory},dst=/inputs,readonly,"
        "bind-recursive=disabled"
    )
    assert approved.path not in mount
    assert arguments.count("--mount") == 1
    assert {path.name for path in adapter._staging.directory.iterdir()} == {
        approved.sha256 + ".parquet",
        second.sha256 + ".parquet",
    }
    assert adapter._staging.directory.stat().st_mode & 0o777 == 0o555
    adapter.terminate_and_reap()


def test_absent_ambiguous_creation_cannot_prove_death_or_release(runtime):
    adapter, control, ledger = runtime
    control.fail = "create"
    with pytest.raises(RuntimeUnavailableError):
        adapter.query(
            QueryRead("SELECT 42", ()),
            adapter.profile.execution_bounds,
            monotonic() + 5,
        )
    control.fail = "inspect"
    with pytest.raises(RuntimeUnavailableError):
        adapter.terminate_and_reap()
    assert ledger.read() and adapter._staging is not None
    assert not any(args[0] == "container" for args, _ in control.calls)


def test_ambiguous_remove_reconciles_absence_only_after_death_proof(runtime):
    adapter, control, ledger = runtime
    adapter.query(
        QueryRead("SELECT 42", ()), adapter.profile.execution_bounds, monotonic() + 5
    )
    control.fail = "rm"
    with pytest.raises(RuntimeUnavailableError):
        adapter.terminate_and_reap()
    original = control.run

    def absent(arguments, **kwargs):
        if arguments[0] == "container":
            return ControlResult(0, b"", b"")
        return original(arguments, **kwargs)

    control.run = absent
    adapter.terminate_and_reap()
    assert ledger.read() is None and adapter._staging is None


def test_staging_cleanup_failure_retains_slot_and_ledger_until_retry(runtime):
    adapter, control, ledger = runtime
    launcher = VerifiedLauncher(
        adapter.profile.execution_bounds, adapter, evidence="controlled"
    )
    reservation = launcher.reserve()
    reservation.query(QueryRead("SELECT 42", ()))
    staging = adapter._staging
    original = staging.close
    staging.close = Mock(side_effect=OSError("controlled cleanup failure"))
    with pytest.raises(RuntimeUnavailableError):
        reservation.close()
    with pytest.raises(AnalyticalBusyError):
        launcher.reserve()
    assert ledger.read() is not None
    staging.close = original
    reservation.close()
    launcher.reserve().close()


@pytest.mark.parametrize("fault", ["timeout", "cancel", "resource", "subprocess"])
def test_attach_failure_keeps_safe_errors_and_bounded_reaping(runtime, fault):
    adapter, control, ledger = runtime
    original = control.run
    error = (
        AnalyticalResourceError
        if fault == "resource"
        else AnalyticalTimeoutError
        if fault in {"timeout", "cancel"}
        else RuntimeUnavailableError
    )

    def failing(arguments, **kwargs):
        if arguments[0] == "start":
            if fault == "cancel":
                adapter.cancel.set()
            raise error("controlled failure")
        return original(arguments, **kwargs)

    control.run = failing
    with pytest.raises(error):
        adapter.query(
            QueryRead("SELECT 42", ()),
            adapter.profile.execution_bounds,
            monotonic() + 5,
        )
    adapter.terminate_and_reap()
    assert ledger.read() is None


def test_foreign_inspect_identity_is_never_reaped(runtime):
    adapter, control, ledger = runtime
    original = control.run

    def foreign(arguments, **kwargs):
        if arguments[0] == "inspect":
            value = json.loads(original(arguments, **kwargs).stdout)
            value["Owner"] = "d" * 32
            return ControlResult(0, json.dumps(value).encode(), b"")
        return original(arguments, **kwargs)

    control.run = foreign
    with pytest.raises(RuntimeUnavailableError):
        adapter.query(
            QueryRead("SELECT 42", ()),
            adapter.profile.execution_bounds,
            monotonic() + 5,
        )
    with pytest.raises(RuntimeUnavailableError):
        adapter.terminate_and_reap()
    assert ledger.read() is not None
    assert not any(args[0] in {"kill", "wait", "rm"} for args, _ in control.calls)


def test_unreaped_host_controller_blocks_all_new_control_until_explicit_retry(
    monkeypatch,
):
    import subprocess

    controller = BoundedDockerControl("unix:///tmp/test.sock", "/missing/docker")
    process = Mock()
    process.pid = 987654321
    process.wait.side_effect = subprocess.TimeoutExpired("controlled", 1)
    controller._unreaped.append(process)
    monkeypatch.setattr(
        "outage_explorer.infrastructure.worker_runtime.docker.os.killpg", Mock()
    )
    with pytest.raises(RuntimeUnavailableError):
        controller.run(
            ("inspect",),
            data=b"",
            deadline=monotonic() + 1,
            stdout_bytes=10,
            stderr_bytes=10,
        )
    with pytest.raises(RuntimeUnavailableError):
        controller.reap(monotonic() + 1)
    assert controller._unreaped == [process]
    process.wait.side_effect = None
    controller.reap(monotonic() + 1)
    assert not controller._unreaped
