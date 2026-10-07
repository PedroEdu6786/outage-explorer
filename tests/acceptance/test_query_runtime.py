"""User-owned real Docker evidence. Default suite never contacts a daemon."""

import json
import os
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

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
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.infrastructure.parquet.schemas import schema_for
from outage_explorer.infrastructure.worker_runtime.docker import DockerRuntime
from outage_explorer.infrastructure.worker_runtime.launcher import VerifiedLauncher
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger
from tests.runtime_validation import (
    CANARY,
    RuntimeHarness,
    measured_workload,
    opted_in,
    read_representative_inputs,
    record_gate,
)


@pytest.fixture
def harness(request):
    if not opted_in(request.config.option.markexpr, os.environ):
        pytest.skip(
            "Requires exact runtime marker selection and explicit nonsecret profile"
        )
    executable = os.environ.get("OUTAGE_RUNTIME_DOCKER_EXECUTABLE") or shutil.which(
        "docker"
    )
    if not executable:
        pytest.fail(
            "Explicit runtime selection has no Docker executable", pytrace=False
        )
    adapter = RuntimeHarness(
        Path(os.environ["OUTAGE_RUNTIME_TEST_PROFILE"]), Path(executable)
    )
    gate = request.node.originalname.removeprefix("test_")
    cleanup_failed = False
    adapter.report.gate(gate, "not_run")
    try:
        adapter.open()
        yield adapter
    finally:
        try:
            adapter.close()
        except Exception:
            adapter.report.gate("cleanup", "failed")
            cleanup_failed = True
        else:
            adapter.report.gate("cleanup", "passed")
        root = Path(adapter.profile.staging_root).parent / "validation-reports"
        adapter.report.write(root / (gate + "-" + uuid4().hex + ".json"))
        if cleanup_failed:
            pytest.fail(
                "Runtime cleanup failed; private ownership retained", pytrace=False
            )


@pytest.fixture
def synthetic_file(tmp_path):
    # Public generator projection with fake entity values, no private provenance.
    path = tmp_path / "public.parquet"
    dataset = PUBLIC_DATASETS[2]
    modeled = schema_for("modeled", dataset.grain)
    schema = pa.schema([modeled.field(c.name) for c in dataset.columns])
    row = {
        "period": date(2026, 4, 2),
        "capacity_mw": Decimal("100"),
        "outage_mw": Decimal("10"),
        "reported_percentage": Decimal("10"),
        "facility": "synthetic",
        "facility_name": "Synthetic",
        "generator": "1",
    }
    pq.write_table(pa.Table.from_pylist([row], schema=schema), path)
    import hashlib

    raw = path.read_bytes()
    return ApprovedFile(str(path), hashlib.sha256(raw).hexdigest(), len(raw), 1)


@pytest.mark.runtime_docker
@record_gate
def test_worker_protocol_and_canonical_output(harness):
    output, seconds = harness.query(QueryRead("SELECT 42 AS answer", ()))
    document = json.loads(output.document)
    assert document["rows"] == [["42"]]
    assert output.retained_row_count == 1
    assert seconds <= harness.profile.worker.execution_seconds
    assert harness.ledger.read() is None
    harness.report.gate(
        "worker_protocol",
        "passed",
        {"seconds": seconds, "output_bytes": len(output.document)},
    )


@pytest.mark.runtime_docker
@record_gate
def test_namespace_network_mount_env_denial(
    harness, synthetic_file, tmp_path, monkeypatch
):
    # These are fake, private host canaries, never real credentials or raw data.
    paths = []
    for category in ("repository", "raw", "cache_sibling", "credentials"):
        path = tmp_path / category
        path.write_text(CANARY)
        paths.append(str(path))
    monkeypatch.setenv(CANARY, CANARY)
    mount = "/inputs/" + synthetic_file.sha256 + ".parquet"
    script = f"""
import os, pathlib, socket
assert os.getuid() == 65534 and os.getgid() == 65534
assert {CANARY!r} not in os.environ
status = pathlib.Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
assert set(os.listdir('/sys/class/net')) == {{'lo'}}
for path in {paths + ["/var/run/docker.sock", "/run/docker.sock"]!r}:
    try:
        pathlib.Path(path).read_bytes()
    except (OSError, PermissionError): pass
    else: raise AssertionError('host read allowed')
assert pathlib.Path({mount!r}).read_bytes()[:4] == b'PAR1'
for path in [{mount!r}, '/opt/worker/validation-write', '/inputs/extra']:
    try:
        pathlib.Path(path).write_bytes(b'fake')
    except OSError: pass
    else: raise AssertionError('mutation allowed')
sock = socket.socket()
sock.settimeout(0.5)
try: sock.connect(('192.0.2.1', 443))
except OSError: pass
else: raise AssertionError('network allowed')
assert os.getpid() == 1
print('denied')
"""
    result = harness.probe(script, (synthetic_file,))
    assert result.code == 0 and result.stdout == b"denied\n"
    # Network/PID/IPC namespaces and only exact files are asserted from safe
    # scalar inspect fields in the creation control, without environment dumps.
    assert Path(synthetic_file.path).read_bytes()[:4] == b"PAR1"


@pytest.mark.runtime_docker
@record_gate
def test_source_replacement_cannot_mutate_staged_input(harness, synthetic_file):
    failure = []

    def replace_source():
        deadline = monotonic() + 8
        while harness.runtime._container is None and monotonic() < deadline:
            Event().wait(0.01)
        if harness.runtime._container is None:
            failure.append(True)
            return
        Path(synthetic_file.path).write_bytes(b"replaced host source")

    mutation = Thread(target=replace_source)
    mutation.start()
    script = f"import hashlib,pathlib,time; p=pathlib.Path('/inputs/{synthetic_file.sha256}.parquet'); time.sleep(1); assert hashlib.sha256(p.read_bytes()).hexdigest() == '{synthetic_file.sha256}'; print('immutable')"
    try:
        response = harness.probe(script, (synthetic_file,))
    finally:
        mutation.join(timeout=10)
    assert not mutation.is_alive() and not failure
    assert response.code == 0 and response.stdout == b"immutable\n"


@pytest.mark.runtime_docker
@record_gate
def test_cpu_memory_process_temp_policy(harness):
    p = harness.profile
    script = f"""
import os, pathlib
root = pathlib.Path('/sys/fs/cgroup')
assert int((root/'memory.max').read_text()) == {p.container_memory_bytes}
assert int((root/'pids.max').read_text()) == {p.process_limit}
quota, period = map(int, (root/'cpu.max').read_text().split())
assert quota / period == {p.cpu_millicores / 1000!r}
mount = next(line.split() for line in pathlib.Path('/proc/mounts').read_text().splitlines() if line.split()[1] == '/tmp')
assert mount[2] == {"ext4" if p.temporary_backend == "quota-disk" else "tmpfs"!r}
assert {{'noexec', 'nosuid', 'nodev'}} <= set(mount[3].split(','))
assert os.statvfs('/tmp').f_blocks * os.statvfs('/tmp').f_frsize <= {p.worker.temporary_bytes}
print('bounded')
"""
    result = harness.probe(script)
    assert result.code == 0 and result.stdout == b"bounded\n"


@pytest.mark.runtime_docker
@record_gate
def test_cpu_quota_throttles_busy_children(harness):
    p = harness.profile
    burners = (p.cpu_millicores + 999) // 1000 + 1
    if burners > min(p.process_limit - 1, 32):
        harness.report.gate("cpu_load_probe", "unsupported")
        pytest.fail(
            "Candidate CPU/PID combination exceeds bounded probe workload",
            pytrace=False,
        )
    script = f"""import os, pathlib, time
before = pathlib.Path('/sys/fs/cgroup/cpu.stat').read_text()
children=[]
for _ in range({burners}):
    pid=os.fork()
    if pid == 0:
        end=time.monotonic()+2
        while time.monotonic() < end: pass
        os._exit(0)
    children.append(pid)
for pid in children: os.waitpid(pid,0)
after=pathlib.Path('/sys/fs/cgroup/cpu.stat').read_text()
def throttled(text): return int(dict(line.split() for line in text.splitlines())['throttled_usec'])
assert throttled(after)>throttled(before)
print('throttled')
"""
    response = harness.probe(script)
    assert response.code == 0 and response.stdout == b"throttled\n"


@pytest.mark.runtime_docker
@record_gate
def test_temporary_quota_enforcement(harness):
    script = """
import errno
try:
    with open('/tmp/fill', 'wb') as stream:
        for _ in range(1024): stream.write(b'x'*65536)
except OSError as error:
    assert error.errno == errno.ENOSPC
    print('limited')
else: raise AssertionError('temporary quota absent')
"""
    result = harness.probe(script)
    assert result.code == 0 and result.stdout == b"limited\n"


@pytest.mark.runtime_docker
@record_gate
def test_memory_quota_enforcement(harness):
    # Allocate beyond the exact ceiling, not indefinitely; require real OOM kill.
    script = f"x = bytearray({harness.profile.container_memory_bytes + 65536}); print('unbounded')"
    result = harness.probe(script)
    assert result.code == 137 and result.stdout != b"unbounded\n"


@pytest.mark.runtime_docker
@record_gate
def test_process_quota_and_descendant_reap(harness):
    script = f"""
import errno, os, signal, time
children = []
try:
    for _ in range({harness.profile.process_limit + 1}):
        pid = os.fork()
        if pid == 0: time.sleep(30); os._exit(0)
        children.append(pid)
except OSError as error:
    assert error.errno == errno.EAGAIN
    print('limited', flush=True)
finally:
    for pid in children: os.kill(pid, signal.SIGKILL)
    for pid in children: os.waitpid(pid, 0)
"""
    result = harness.probe(script)
    assert result.code == 0 and result.stdout == b"limited\n"
    # Container removal is verified separately from the parent's own exit.
    assert harness.ledger.read() is None


@pytest.mark.runtime_docker
@pytest.mark.parametrize(
    "kind",
    [
        "stalled",
        "stalled_input",
        "overflow",
        "stderr",
        "crash",
        "descendants",
        "cancel",
    ],
)
@record_gate
def test_deadline_crash_io_cleanup(harness, kind):
    scripts = {
        "stalled": "import time; time.sleep(30)",
        "stalled_input": "import time; time.sleep(30)",
        "cancel": "import time; time.sleep(30)",
        "stderr": "import os; os.write(2,b'x'*131072)",
        "overflow": "import os; os.write(1,b'x'*131072)",
        "crash": "import os; os._exit(2)",
        "descendants": "import os,time; os.fork(); time.sleep(30)",
    }
    started = monotonic()
    if kind == "crash":
        assert harness.probe(scripts[kind], seconds=3).code == 2
    else:
        with pytest.raises((AnalyticalTimeoutError, AnalyticalResourceError)):
            cancel = Event()
            if kind == "cancel":
                cancel.set()
            harness.probe(
                scripts[kind],
                seconds=3,
                limit=8192,
                data=b"x" * 131072 if kind == "stalled_input" else b"",
                cancel=cancel,
            )
    assert (
        monotonic() - started
        < 3 + harness.profile.termination_seconds + harness.profile.control_seconds
    )
    listing = harness.command(
        (
            "container",
            "ls",
            "--all",
            "--filter",
            "label=outage.analytical.owner=" + harness.ledger.owner,
            "--format",
            "{{.ID}}",
        )
    )
    assert listing.code == 0 and listing.stdout.strip() == b""
    assert harness.ledger.read() is None


class FailedRemoval:
    """Induced control failure against a real container; never stop the daemon."""

    def __init__(self, real):
        self.real, self.fail = real, True

    def run(self, arguments, **kwargs):
        if self.fail and arguments[0] == "rm":
            raise RuntimeUnavailableError("Synthetic cleanup outage")
        return self.real.run(arguments, **kwargs)


@pytest.mark.runtime_docker
@record_gate
def test_failed_reap_preserves_slot_pins_and_recovers(harness, synthetic_file):
    control = FailedRemoval(harness.control)
    harness.runtime.control = control
    launcher = VerifiedLauncher(
        harness.profile.execution_bounds,
        harness.runtime,
        evidence="candidate validation only",
    )

    class Pin:
        closed = False

        def close(self):
            self.closed = True

    pin = Pin()
    reservation = launcher.reserve()
    reservation.handoff((pin,))
    try:
        reservation.query(
            QueryRead(
                "SELECT * FROM generators", ((PUBLIC_DATASETS[2], (synthetic_file,)),)
            )
        )
        with pytest.raises(RuntimeUnavailableError):
            reservation.close()
        assert launcher.active and not pin.closed
        record = harness.ledger.read()
        assert record is not None
        assert list(Path(record["staging"]).glob("*.parquet"))
        with pytest.raises(AnalyticalBusyError):
            launcher.reserve()
        # Logical expiry/cleanup cannot release unresolved ownership.
        launcher.recovery.reconcile()
        assert launcher.active and not pin.closed
    finally:
        control.fail = False
        launcher.recovery.reconcile()
    assert not launcher.active and pin.closed and harness.ledger.read() is None


@pytest.mark.runtime_docker
@record_gate
def test_restart_reconciles_owned_container(harness):
    # Create real stopped container, persist intent, then lose in-memory owner.
    runtime = harness.runtime
    runtime.prepare_inputs((), monotonic() + 5)
    arguments = runtime._create_arguments()
    harness.ledger.creating()
    runtime._create_attempted = True
    created = harness.command(arguments)
    assert created.code == 0
    identity = created.stdout.decode().strip()
    assert len(identity) == 64
    if runtime._spill is not None:
        runtime._spill.release()  # emulate process death, retaining disk intent
    harness.ledger.close()
    recovered = OwnershipLedger(harness.ledger.root, uuid4().hex)
    recovered.open()
    recovering = DockerRuntime(harness.profile, harness.control, recovered)
    harness.ledger, harness.runtime = recovered, recovering
    recovering.recover_owned()
    assert recovered.read() is None


@pytest.mark.runtime_docker
@record_gate
def test_ambiguous_create_and_daemon_failure(harness):
    real = harness.control

    class LostCreate:
        def run(self, arguments, **kwargs):
            response = real.run(arguments, **kwargs)
            if arguments[0] == "create":
                raise RuntimeUnavailableError("Synthetic lost create response")
            return response

    harness.runtime.control = LostCreate()
    try:
        with pytest.raises(RuntimeUnavailableError):
            harness.runtime.query(
                QueryRead("SELECT 42", ()),
                harness.profile.execution_bounds,
                monotonic() + 10,
            )
        assert harness.ledger.read() is not None
    finally:
        harness.runtime.control = real
        harness.runtime.terminate_and_reap()
    assert harness.ledger.read() is None
    from outage_explorer.infrastructure.worker_runtime.docker import (
        BoundedDockerControl,
    )

    unavailable = BoundedDockerControl(
        "unix:///private/tmp/outage-validation-missing-" + uuid4().hex, real.executable
    )
    response = unavailable.run(
        ("version", "--format", "{{.Server.Version}}"),
        data=b"",
        deadline=monotonic() + harness.profile.control_seconds,
        stdout_bytes=1024,
        stderr_bytes=65536,
    )
    assert response.code != 0


@pytest.mark.runtime_docker
@record_gate
def test_disk_spill_readiness_requires_supported_backend(harness):
    assert harness.profile.temporary_backend == "quota-disk"
    script = f"""
import errno, os, pathlib, subprocess
assert not any(line.split()[1] == '/dev/shm' for line in pathlib.Path('/proc/mounts').read_text().splitlines())
try: pathlib.Path('/dev/shm/denied').write_bytes(b'x')
except OSError: pass
else: raise AssertionError('extra writable temporary mount')
volume = os.statvfs('/tmp')
assert 0 < volume.f_files <= {harness.profile.temporary_inodes}
files = []
try:
    for index in range(1024):
        stream = open('/tmp/fill-' + str(index), 'wb', buffering=0)
        files.append(stream)
        os.unlink(stream.name)
        stream.write(b'x' * 65536)
except OSError as error:
    assert error.errno == errno.ENOSPC
else: raise AssertionError('aggregate open/unlinked quota absent')
finally:
    for stream in files: stream.close()
path = pathlib.Path('/tmp/execute')
path.write_text('#!/bin/sh\\nexit 0\\n')
path.chmod(0o700)
try: subprocess.run([str(path)], check=True)
except OSError as error: assert error.errno == errno.EACCES
else: raise AssertionError('noexec absent')
print('disk-bounded')
"""
    response = harness.probe(script)
    assert response.code == 0 and response.stdout == b"disk-bounded\n"
    inode_script = f"""
import errno, os
try:
    for index in range({harness.profile.temporary_inodes + 1}):
        fd = os.open('/tmp/inode-' + str(index), os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
except OSError as error: assert error.errno == errno.ENOSPC
else: raise AssertionError('inode quota absent')
print('inodes-bounded')
"""
    response = harness.probe(inode_script)
    assert response.code == 0 and response.stdout == b"inodes-bounded\n"
    assert not any(
        path.name.startswith("execution-")
        for path in Path(harness.profile.temporary_root).iterdir()
    )
    harness.report.gate("disk_quota", "passed")


@pytest.mark.runtime_measurements
@record_gate
def test_representative_cold_warm_and_overlap_measurements(harness):
    source = os.environ.get("OUTAGE_RUNTIME_MEASUREMENT_INPUTS")
    if not source:
        harness.report.gate("representative_inputs", "not_run")
        pytest.fail(
            "Explicit measurements require verified public input manifest",
            pytrace=False,
        )
    if not Path("/proc/meminfo").is_file():
        harness.report.gate("host_memory_sampler", "unsupported")
        pytest.fail(
            "Representative host measurement currently requires Linux procfs",
            pytrace=False,
        )
    inputs = read_representative_inputs(Path(source), harness.profile)
    harness.report.document["workload_identity"] = inputs.identity
    metrics = measured_workload(harness, inputs)
    harness.report.gate("representative_measurements", "failed", metrics)
    harness.report.gate("external_refresh_transfer", "not_run")
    assert metrics["samples"] > 0 and metrics["api_requests"] > 0
    assert metrics["sampling_failures"] == 0 and metrics["api_failures"] == 0
    assert metrics["container_memory_peak_bytes"] > 0
    assert (
        metrics["container_memory_peak_bytes"] <= harness.profile.container_memory_bytes
    )
    assert metrics["staging_peak_bytes"] <= harness.profile.staging_bytes
    assert metrics["cache_peak_bytes"] <= harness.profile.cache_bytes
    assert metrics["spool_index_peak_bytes"] <= harness.profile.result_bytes
    for label in ("old", "cold", "warm"):
        assert (
            metrics[label + "_prepare_seconds"]
            < harness.profile.worker.preparation_seconds
        )
        assert (
            metrics[label + "_aggregate_seconds"]
            < harness.profile.worker.execution_seconds
        )
        assert (
            metrics[label + "_execution_seconds"]
            < harness.profile.worker.execution_seconds
        )
    assert (
        metrics["warm_cumulative_local_copy_bytes"]
        == metrics["cold_cumulative_local_copy_bytes"]
    )
    harness.report.gate("representative_measurements", "passed", metrics)
