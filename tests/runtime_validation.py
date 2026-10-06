"""Explicit contributor validation only; never imported by product composition.

The candidate launcher may be exercised without fabricating readiness evidence.
All Docker operations use the bounded production controller and isolation flags.
"""

import hashlib
import http.client
import json
import os
import re
import resource
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import wraps
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

import pyarrow.parquet as pq

from outage_explorer.application.errors import (
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.analytical_inputs import ApprovedFile
from outage_explorer.application.ports.execution import PreviewRead, QueryRead
from outage_explorer.domain.datasets import PUBLIC_DATASETS
from outage_explorer.domain.preview_keys import follows_preview_key
from outage_explorer.infrastructure.query_results.preview_encoding import (
    PreviewEncoding,
)
from outage_explorer.infrastructure.query_results.store import (
    BoundedQueryResults,
    ResultBounds,
)
from outage_explorer.infrastructure.worker_runtime.configuration import (
    read_runtime_config,
)
from outage_explorer.infrastructure.worker_runtime.docker import (
    BoundedDockerControl,
    DockerRuntime,
)
from outage_explorer.infrastructure.worker_runtime.inputs import stage_inputs
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger


def record_gate(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        harness = kwargs["harness"]
        name = function.__name__.removeprefix("test_")
        try:
            result = function(*args, **kwargs)
        except BaseException:
            harness.report.gate(name, "failed")
            raise
        harness.report.gate(name, "passed")
        return result

    return wrapped


MARKERS = frozenset({"runtime_docker", "runtime_measurements"})
CANARY = "OUTAGE_VALIDATION_FAKE_SECRET_DO_NOT_PROPAGATE"
MEASUREMENT_MANIFEST_BYTES = 1_048_576


def opted_in(mark_expression, environment):
    """Configuration alone never opts the default suite into daemon operations."""
    words = re.findall(r"[A-Za-z_][A-Za-z_0-9]*", mark_expression or "")
    # Reject negations/compound expressions: only the documented exact selection.
    return (
        len(words) == 1
        and words[0] in MARKERS
        and bool(environment.get("OUTAGE_RUNTIME_TEST_PROFILE"))
    )


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_mode & 0o077
        or any(p.is_symlink() for p in path.parents)
    ):
        raise ValueError("Validation requires private owned directories")


class EvidenceReport:
    """Allowlisted bounded evidence; never serializes exceptions or raw output."""

    def __init__(self, profile):
        self.document = {
            "schema": 1,
            "profile_identity": profile.identity,
            "image_id": profile.image_id,
            "platform": profile.platform,
            "daemon_version": profile.daemon_version,
            "temporary_backend": profile.temporary_backend,
            "readiness": "unreviewed",
            "gates": {},
        }

    def gate(self, name, status, metrics=None):
        if (
            re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) is None
            or status not in {"passed", "failed", "unsupported", "not_run"}
            or len(self.document["gates"]) >= 64
        ):
            raise ValueError("Invalid evidence gate")
        clean = {}
        for key, value in (metrics or {}).items():
            if (
                re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) is None
                or type(value) not in (int, float, bool)
                or isinstance(value, float)
                and not (-1e100 < value < 1e100)
                or len(clean) >= 64
            ):
                raise ValueError("Only bounded numeric evidence is accepted")
            clean[key] = value
        self.document["gates"][name] = {"status": status, "metrics": clean}

    def write(self, path):
        raw = json.dumps(self.document, sort_keys=True, separators=(",", ":")).encode()
        if len(raw) > 65_536:
            raise ValueError("Evidence size exceeded")
        private_directory(path.parent)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
        return hashlib.sha256(raw).hexdigest()


class RuntimeHarness:
    def __init__(self, config_path, executable):
        self.profile, _ = read_runtime_config(config_path)
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("Explicit absolute Docker executable required")
        self.control = BoundedDockerControl(
            self.profile.daemon_endpoint, str(executable)
        )
        self.report = EvidenceReport(self.profile)
        self.ledger = OwnershipLedger(
            Path(self.profile.staging_root).parent / ("validation-" + uuid4().hex),
            uuid4().hex,
        )
        self.runtime = DockerRuntime(self.profile, self.control, self.ledger)
        self._opened = False

    def command(self, arguments, *, data=b"", seconds=None, limit=8192):
        return self.control.run(
            tuple(arguments),
            data=data,
            deadline=monotonic() + (seconds or self.profile.control_seconds),
            stdout_bytes=limit,
            stderr_bytes=self.profile.stderr_bytes,
        )

    def open(self):
        # Only safe scalar fields, never full inspection (.Config.Env is forbidden).
        daemon = self.command(
            (
                "version",
                "--format",
                "{{.Server.Version}} {{.Server.Os}}/{{.Server.Arch}}",
            )
        )
        if daemon.code or daemon.stdout.decode().strip() != (
            self.profile.daemon_version + " " + self.profile.platform
        ):
            raise ValueError("Daemon identity does not match configured profile")
        image = self.command(
            ("image", "inspect", "--format", "{{.Id}}", self.profile.image_id)
        )
        if image.code or image.stdout.decode().strip() != self.profile.image_id:
            raise ValueError("Image identity does not match configured profile")
        for root in (
            self.profile.staging_root,
            self.profile.cache_root,
            self.profile.result_root,
        ):
            private_directory(Path(root))
            if any(Path(root).iterdir()):
                raise ValueError("Validation roots must be empty and dedicated")
        self.ledger.open()
        self._opened = True
        self.report.gate("identity", "passed")
        self.runtime.validate_temporary_backend()
        self.report.gate(
            "disk_quota",
            "not_run"
            if self.profile.temporary_backend == "quota-disk"
            else "unsupported",
        )

    def close(self):
        if not self._opened:
            return
        # On uncertain reap preserve ledger/staging, never shutil unresolved paths.
        self.runtime.terminate_and_reap()
        self.ledger.close()
        shutil.rmtree(self.ledger.root)
        self._opened = False

    def query(self, request):
        started = monotonic()
        try:
            output = self.runtime.query(
                request,
                self.profile.execution_bounds,
                started + self.profile.worker.execution_seconds,
            )
            return output, monotonic() - started
        finally:
            self.runtime.terminate_and_reap()

    def preview(self, request):
        started = monotonic()
        try:
            output = self.runtime.preview(
                request,
                self.profile.execution_bounds,
                started + self.profile.worker.execution_seconds,
            )
            return output, monotonic() - started
        finally:
            self.runtime.terminate_and_reap()

    def probe(
        self, script, files=(), *, seconds=None, limit=8192, data=b"", cancel=None
    ):
        """Same flags/image/file staging; entrypoint override is probe-only."""
        if len(script.encode()) > 16384 or len(data) > self.profile.request_bytes:
            raise ValueError("Bounded synthetic probe required")
        deadline = monotonic() + (seconds or self.profile.worker.execution_seconds)
        self.runtime._staging = stage_inputs(self.profile, files, deadline)
        self.runtime.prepare_temporary()
        arguments = self.runtime._create_arguments()
        arguments = (
            *arguments[:-1],
            "--entrypoint",
            "python",
            arguments[-1],
            "-c",
            script,
        )
        try:
            self.ledger.creating()
            self.runtime._create_attempted = True
            created = self.command(arguments)
            identity = created.stdout.decode().strip()
            if created.code or re.fullmatch(r"[0-9a-f]{64}", identity) is None:
                raise RuntimeUnavailableError("Probe creation failed")
            self.runtime._container = identity
            namespace = self.command(
                (
                    "inspect",
                    "--format",
                    "{{.HostConfig.PidMode}}|{{.HostConfig.IpcMode}}|{{.HostConfig.NetworkMode}}",
                    identity,
                )
            )
            if namespace.code or namespace.stdout.strip() != b"|none|none":
                raise RuntimeUnavailableError("Probe namespace policy mismatch")
            return self.control.run(
                ("start", "--attach", "--interactive", identity),
                data=data,
                deadline=deadline,
                stdout_bytes=limit,
                stderr_bytes=self.profile.stderr_bytes,
                cancel=cancel,
            )
        finally:
            self.runtime.terminate_and_reap()


@dataclass(frozen=True)
class RepresentativeInputs:
    identity: str
    old: tuple
    current: tuple
    refresh_pid: int
    api_port: int
    api_pid: int


def read_representative_inputs(path, profile, *, analytical_only=False):
    """Only pre-existing, public projection files. No fetch, refresh or publish."""
    if path.is_symlink():
        raise ValueError("Invalid representative manifest")
    with path.open("rb") as stream:
        raw = stream.read(MEASUREMENT_MANIFEST_BYTES + 1)
    if len(raw) > MEASUREMENT_MANIFEST_BYTES:
        raise ValueError("Representative manifest too large")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate representative key")
            value[key] = item
        return value

    document = json.loads(raw, object_pairs_hook=unique)
    required = (
        {"old", "current"}
        if analytical_only
        else {"old", "current", "refresh_pid", "api_port", "api_pid"}
    )
    if not isinstance(document, dict) or set(document) != required:
        raise ValueError("Invalid representative manifest")
    if not analytical_only and (
        type(document["refresh_pid"]) is not int
        or document["refresh_pid"] <= 1
        or document["refresh_pid"] == os.getpid()
        or type(document["api_pid"]) is not int
        or document["api_pid"] <= 1
        or document["api_pid"] == os.getpid()
        or document["api_pid"] == document["refresh_pid"]
        or type(document["api_port"]) is not int
        or not 1 <= document["api_port"] <= 65535
    ):
        raise ValueError("Already running refresh and loopback API required")
    total = 0
    count = 0
    deadline = monotonic() + profile.worker.preparation_seconds

    def snapshot(name):
        nonlocal total, count
        mapping = document[name]
        if not isinstance(mapping, dict) or set(mapping) != {
            d.id for d in PUBLIC_DATASETS
        }:
            raise ValueError("All three representative grains required")
        relations = []
        for dataset in PUBLIC_DATASETS:
            items = mapping[dataset.id]
            if not isinstance(items, list) or not items:
                raise ValueError("Usable representative inputs required")
            files = []
            for item in items:
                if not isinstance(item, dict) or set(item) != {
                    "path",
                    "sha256",
                    "byte_count",
                    "rows",
                }:
                    raise ValueError("Invalid representative descriptor")
                approved = ApprovedFile(**item)
                source = Path(approved.path)
                if (
                    not source.is_absolute()
                    or source.is_symlink()
                    or any(p.is_symlink() for p in source.parents)
                    or not source.is_file()
                    or re.fullmatch(r"[0-9a-f]{64}", approved.sha256) is None
                    or type(approved.byte_count) is not int
                    or approved.byte_count <= 0
                    or type(approved.rows) is not int
                    or approved.rows <= 0
                ):
                    raise ValueError("Invalid representative public file")
                total += approved.byte_count
                count += 1
                if total > profile.cache_bytes or count > profile.input_files:
                    raise ValueError("Representative input budget exceeded")
                digest = hashlib.sha256()
                observed = 0
                with source.open("rb") as stream:
                    while chunk := stream.read(65536):
                        observed += len(chunk)
                        if observed > approved.byte_count or monotonic() >= deadline:
                            raise ValueError(
                                "Representative verification budget exceeded"
                            )
                        digest.update(chunk)
                parquet = pq.ParquetFile(source)
                if (
                    source.stat().st_size != approved.byte_count
                    or digest.hexdigest() != approved.sha256
                    or parquet.metadata.num_rows != approved.rows
                    or parquet.schema_arrow.names != [c.name for c in dataset.columns]
                ):
                    raise ValueError("Representative public projection mismatch")
                files.append(approved)
            relations.append((dataset, tuple(files)))
        return tuple(relations)

    old, current = snapshot("old"), snapshot("current")
    return RepresentativeInputs(
        hashlib.sha256(raw).hexdigest(),
        old,
        current,
        document.get("refresh_pid"),
        document.get("api_port"),
        document.get("api_pid"),
    )


class SystemClock:
    def now(self):
        return datetime.now(UTC)


def directory_bytes(root):
    return sum(
        p.lstat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink()
    )


def process_token(pid):
    """Linux start ticks reject reused PIDs; never retain comm/argv/environment."""
    os.kill(pid, 0)
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    if fields[0] == "Z":
        raise ValueError("Overlap process is not running")
    return int(fields[19])


class OverlapSampler:
    """Bounded numeric sampling; no process arguments/environment or API identity."""

    def __init__(self, harness, inputs):
        self.harness, self.inputs = harness, inputs
        self.stop = Event()
        self.thread = Thread(target=self._sample, daemon=True)
        self.process_tokens = (
            {pid: process_token(pid) for pid in (inputs.refresh_pid, inputs.api_pid)}
            if inputs is not None
            else {}
        )
        self.metrics = {
            "samples": 0,
            "api_requests": 0,
            "api_failures": 0,
            "api_max_seconds": 0.0,
            "container_memory_peak_bytes": 0,
            "container_cpu_peak_percent": 0.0,
            "host_available_memory_min_bytes": 2**63 - 1,
            "refresh_rss_peak_bytes": 0,
            "refresh_cpu_seconds": 0.0,
            "api_rss_peak_bytes": 0,
            "api_cpu_seconds": 0.0,
            "staging_peak_bytes": 0,
            "cache_peak_bytes": 0,
            "spool_index_peak_bytes": 0,
            "sampling_failures": 0,
            "sampling_host_memory_failures": 0,
            "sampling_filesystem_failures": 0,
            "sampling_container_control_failures": 0,
            "container_control_timeouts": 0,
            "container_control_nonzero": 0,
            "sampling_container_decode_failures": 0,
            "sampling_overlap_process_failures": 0,
            "sampling_api_probe_failures": 0,
            "sampling_other_failures": 0,
            "spill_peak_bytes": 0,
        }

    def _sample(self):
        while not self.stop.is_set():
            stage = "other"
            try:
                if self.inputs is not None:
                    stage = "overlap_process"
                    for pid, token in self.process_tokens.items():
                        if process_token(pid) != token:
                            raise ValueError("Overlap process identity changed")
                    os.kill(self.inputs.refresh_pid, 0)
                    # ps selects only numeric RSS/CPU time, never args/environment.
                    import subprocess

                    raw = subprocess.run(
                        (
                            "/bin/ps",
                            "-p",
                            str(self.inputs.refresh_pid),
                            "-o",
                            "rss=,time=",
                        ),
                        capture_output=True,
                        timeout=1,
                        check=True,
                        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                    ).stdout
                    if len(raw) > 256:
                        raise ValueError("Sampling output exceeded")
                    rss, cpu = raw.decode().split()
                    fields = cpu.split(":")
                    if len(fields) not in (2, 3):
                        raise ValueError("Unsupported process CPU format")
                    cpu_seconds = sum(
                        float(x) * 60**i for i, x in enumerate(reversed(fields))
                    )
                    self.metrics["refresh_rss_peak_bytes"] = max(
                        self.metrics["refresh_rss_peak_bytes"], int(rss) * 1024
                    )
                    self.metrics["refresh_cpu_seconds"] = max(
                        self.metrics["refresh_cpu_seconds"], cpu_seconds
                    )
                    api_stat = (
                        Path(f"/proc/{self.inputs.api_pid}/stat")
                        .read_text()
                        .rsplit(")", 1)[1]
                        .split()
                    )
                    self.metrics["api_rss_peak_bytes"] = max(
                        self.metrics["api_rss_peak_bytes"],
                        int(api_stat[21]) * os.sysconf("SC_PAGE_SIZE"),
                    )
                    self.metrics["api_cpu_seconds"] = max(
                        self.metrics["api_cpu_seconds"],
                        (int(api_stat[11]) + int(api_stat[12]))
                        / os.sysconf("SC_CLK_TCK"),
                    )
                # Linux MemAvailable is measured, not total installed RAM.
                stage = "host_memory"
                meminfo = Path("/proc/meminfo")
                if not meminfo.is_file():
                    raise ValueError("Host available-memory sampler requires Linux")
                available = next(
                    line
                    for line in meminfo.read_text().splitlines()
                    if line.startswith("MemAvailable:")
                )
                self.metrics["host_available_memory_min_bytes"] = min(
                    self.metrics["host_available_memory_min_bytes"],
                    int(available.split()[1]) * 1024,
                )
                stage = "filesystem"
                for name, root in (
                    ("staging_peak_bytes", self.harness.profile.staging_root),
                    ("cache_peak_bytes", self.harness.profile.cache_root),
                    ("spill_peak_bytes", self.harness.profile.temporary_root),
                    ("spool_index_peak_bytes", self.harness.profile.result_root),
                ):
                    self.metrics[name] = max(
                        self.metrics[name], directory_bytes(Path(root))
                    )
                identity = self.harness.runtime._container
                if identity:
                    stage = "container_control"
                    response = self.harness.command(
                        (
                            "stats",
                            "--no-stream",
                            "--format",
                            "{{.MemUsage}}|{{.CPUPerc}}",
                            identity,
                        ),
                        seconds=2,
                        limit=256,
                    )
                    if response.code:
                        self.metrics["container_control_nonzero"] += 1
                        raise ValueError("Container sampling unavailable")
                    stage = "container_decode"
                    memory, cpu = response.stdout.decode().strip().split("|")
                    number, unit = re.fullmatch(
                        r"([0-9.]+)([A-Za-z]+).*", memory
                    ).groups()
                    factor = {
                        "B": 1,
                        "KiB": 1024,
                        "MiB": 1024**2,
                        "GiB": 1024**3,
                        "kB": 1000,
                        "MB": 1000**2,
                        "GB": 1000**3,
                    }[unit]
                    self.metrics["container_memory_peak_bytes"] = max(
                        self.metrics["container_memory_peak_bytes"],
                        int(float(number) * factor),
                    )
                    self.metrics["container_cpu_peak_percent"] = max(
                        self.metrics["container_cpu_peak_percent"],
                        float(cpu.removesuffix("%")),
                    )
                if self.inputs is not None:
                    stage = "api_probe"
                    started = monotonic()
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", self.inputs.api_port, timeout=1
                    )
                    try:
                        connection.request("GET", "/health")
                        response = connection.getresponse()
                        if response.status != 200 or len(response.read(8193)) > 8192:
                            self.metrics["api_failures"] += 1
                    finally:
                        connection.close()
                    self.metrics["api_requests"] += 1
                    self.metrics["api_max_seconds"] = max(
                        self.metrics["api_max_seconds"], monotonic() - started
                    )
                self.metrics["samples"] += 1
            except Exception as error:
                if stage == "container_control" and isinstance(
                    error, AnalyticalTimeoutError
                ):
                    self.metrics["container_control_timeouts"] += 1
                self.metrics["sampling_failures"] += 1
                self.metrics["sampling_" + stage + "_failures"] += 1
            self.stop.wait(0.1)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeUnavailableError("Measurement sampler did not stop")


def copy_verified(file, target, deadline):
    """Copy exact bounded bytes; source mutation never becomes a warm cache hit."""
    source_fd = os.open(file.path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    observed = 0
    try:
        with os.fdopen(source_fd, "rb") as source, target.open("xb") as destination:
            while chunk := source.read(65536):
                observed += len(chunk)
                if observed > file.byte_count or monotonic() >= deadline:
                    raise ValueError("Verified-copy preparation budget exceeded")
                digest.update(chunk)
                destination.write(chunk)
        if observed != file.byte_count or digest.hexdigest() != file.sha256:
            raise ValueError("Representative input changed during copy")
        os.chmod(target, 0o400)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return observed


def measured_workload(
    harness, inputs, *, analytical_only=False, include_previews=False
):
    """Copy-only cold/warm cache; old snapshot retained; real query/spool/index."""
    profile = harness.profile
    sampler = OverlapSampler(harness, None if analytical_only else inputs)
    root = Path(profile.cache_root) / ("validation-" + uuid4().hex)
    private_directory(root)
    results = BoundedQueryResults(
        Path(profile.result_root),
        SystemClock(),
        ResultBounds(
            profile.results_per_user, profile.result_count, profile.result_bytes, 65_536
        ),
    )
    sampler_started = False
    failed = False
    copied = 0
    before = resource.getrusage(resource.RUSAGE_SELF)
    metrics = {}
    preview_metrics = {}
    # Aggregate scans plus sort/output encode; zero new source work.
    sql = " UNION ALL ".join(
        f"SELECT '{d.id}' AS dataset, COUNT(*) AS rows, SUM(outage_mw) AS outage FROM {d.id}"
        for d in PUBLIC_DATASETS
    )
    try:
        results.start()
        cached = {}
        sampler.start()
        sampler_started = True
        for label, relations in (
            ("old", inputs.old),
            ("cold", inputs.current),
            ("warm", inputs.current),
        ):
            started = monotonic()
            preparation_deadline = started + profile.worker.preparation_seconds
            prepared = []
            for dataset, files in relations:
                approved = []
                for file in files:
                    if file.sha256 not in cached:
                        target = root / (file.sha256 + ".parquet")
                        copied += copy_verified(file, target, preparation_deadline)
                        cached[file.sha256] = ApprovedFile(
                            str(target), file.sha256, file.byte_count, file.rows
                        )
                    approved.append(cached[file.sha256])
                prepared.append((dataset, tuple(approved)))
            metrics[label + "_prepare_seconds"] = monotonic() - started
            metrics[label + "_cumulative_local_copy_bytes"] = copied
            aggregate, aggregate_latency = harness.query(
                QueryRead(sql, tuple(prepared))
            )
            metrics[label + "_aggregate_seconds"] = aggregate_latency
            metrics[label + "_aggregate_rows"] = aggregate.retained_row_count
            output, latency = harness.query(
                QueryRead(
                    "SELECT * FROM generators ORDER BY period, facility, generator",
                    tuple(prepared[-1:]),
                )
            )
            metrics[label + "_execution_seconds"] = latency
            # Complete verifies canonical encoding, writes immutable spool/index.
            reservation = results.reserve("validation-" + label)
            try:
                identity = reservation.complete(
                    output,
                    frozenset(d.grain for d in PUBLIC_DATASETS),
                    "validation-" + label,
                    100,
                )
            finally:
                reservation.close()
            reader = results.acquire(identity.id, "validation-" + label)
            try:
                page_started = monotonic()
                reader.page(1)
                metrics[label + "_page_seconds"] = monotonic() - page_started
            finally:
                reader.close()
            metrics[label + "_output_bytes"] = len(output.document)
            metrics[label + "_retained_rows"] = output.retained_row_count
            metrics["spool_index_peak_bytes"] = directory_bytes(
                Path(profile.result_root)
            )
            if include_previews:
                measure_previews(harness, prepared, label, preview_metrics)
        metrics["local_copy_bytes"] = copied
        metrics["old_and_current_retained_bytes"] = directory_bytes(root)
    except Exception:
        failed = True
        raise
    finally:
        if sampler_started:
            sampler.close()
        if failed:
            if include_previews:
                harness.report.gate("preview_workload", "failed", preview_metrics)
            metrics["local_copy_bytes"] = copied
            metrics.update(sampler.metrics)
            harness.report.gate("analytical_progress", "failed", metrics)
        results.close()
        shutil.rmtree(root)
    after = resource.getrusage(resource.RUSAGE_SELF)
    spool_peak = metrics["spool_index_peak_bytes"]
    metrics.update(sampler.metrics)
    metrics["spool_index_peak_bytes"] = max(
        spool_peak, metrics["spool_index_peak_bytes"]
    )
    metrics["harness_cpu_seconds"] = (after.ru_utime + after.ru_stime) - (
        before.ru_utime + before.ru_stime
    )
    # Linux ru_maxrss is KiB. Measurements require Linux above; never guess Darwin.
    metrics["harness_rss_peak_bytes"] = after.ru_maxrss * 1024
    if hasattr(harness, "report"):
        harness.report.gate(
            "sql_workload", "passed", {"executions": 6, "page_reads": 3}
        )
    if include_previews:
        harness.report.gate("preview_workload", "passed", preview_metrics)
    return metrics


def measure_previews(harness, relations, label, metrics):
    """Actual worker previews: first/default, maximum continuation, changed dates."""
    encoding = PreviewEncoding(harness.profile.encoding_bounds)
    for dataset, files in relations:
        prefix = label + "_" + dataset.id
        first, first_seconds = harness.preview(
            PreviewRead(dataset, files, None, None, None, 100)
        )
        if not first.rows or not first.keys:
            raise ValueError("Representative preview empty")
        following, next_seconds = harness.preview(
            PreviewRead(dataset, files, None, None, first.keys[-1], 500)
        )
        start, end = date(2026, 10, 2), date(2026, 10, 5)
        filtered, filter_seconds = harness.preview(
            PreviewRead(dataset, files, start, end, None, 500)
        )
        encoded_bytes = 0
        for output, size, after, filtered_range in (
            (first, 100, None, False),
            (following, 500, first.keys[-1], False),
            (filtered, 500, None, True),
        ):
            if (
                len(output.rows) != len(output.keys)
                or len(output.rows) > size
                or any(
                    not follows_preview_key(b, a)
                    for a, b in zip(output.keys, output.keys[1:], strict=False)
                )
                or after is not None
                and any(not follows_preview_key(key, after) for key in output.keys)
                or filtered_range
                and any(
                    not start.isoformat() <= key[0] <= end.isoformat()
                    for key in output.keys
                )
            ):
                raise ValueError("Invalid representative preview continuation")
            document = {
                "columns": encoding.columns(dataset.columns),
                "rows": [encoding.row(dataset.columns, row) for row in output.rows],
                "has_more": output.has_more,
            }
            observed = encoding.bytes(document)
            if observed > harness.profile.worker.output_bytes:
                raise ValueError("Representative preview output exceeded")
            encoded_bytes += observed
        metrics[prefix + "_first_seconds"] = first_seconds
        metrics[prefix + "_next_seconds"] = next_seconds
        metrics[prefix + "_filter_seconds"] = filter_seconds
        metrics[prefix + "_rows"] = len(first.rows) + len(following.rows)
        metrics[prefix + "_filtered_rows"] = len(filtered.rows)
        metrics[prefix + "_encoded_bytes"] = encoded_bytes
