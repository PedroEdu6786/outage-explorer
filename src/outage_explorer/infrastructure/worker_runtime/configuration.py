"""Inert nonsecret profile and matching readiness contracts; no runtime probing."""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from outage_explorer.application.errors import RuntimeUnavailableError
from outage_explorer.application.ports.execution import ExecutionBounds
from outage_explorer.domain.query_results import LIFETIME_SECONDS
from outage_explorer.infrastructure.query_results.encoding import (
    EncodingBounds,
    canonical_json,
)

WORKER_PROTOCOL_VERSION = 2


@dataclass(frozen=True)
class WorkerImageLimits:
    """Internal v1 image limits; changes require a new matching image/evidence."""

    preparation_seconds: int = 30
    overall_seconds: int = 40
    execution_seconds: int = 10
    memory_bytes: int = 134_217_728
    temporary_bytes: int = 16_777_216
    output_bytes: int = 1_048_576
    max_cell_bytes: int = 1_048_576
    max_depth: int = 16
    max_nested_items: int = 10_000
    max_columns: int = 100
    max_schema_bytes: int = 65_536

    def __post_init__(self) -> None:
        if any(type(v) is not int or v <= 0 for v in vars(self).values()):
            raise ValueError("Invalid analytical worker limits")
        if self.execution_seconds > 10 or self.output_bytes > 1_048_576:
            raise ValueError("Analytical worker limits exceed accepted caps")


@dataclass(frozen=True)
class RuntimeProfile:
    image_id: str
    daemon_endpoint: str
    platform: str
    daemon_version: str
    filesystem_identity: str
    staging_root: str = "/tmp/outage-analytical/staging"
    cache_root: str = "/tmp/outage-analytical/cache"
    result_root: str = "/tmp/outage-analytical/results"
    preview_lifetime_seconds: int = LIFETIME_SECONDS
    result_lifetime_seconds: int = LIFETIME_SECONDS
    engine_version: str = "1.5.6"
    protocol_version: int = WORKER_PROTOCOL_VERSION
    worker: WorkerImageLimits = field(default_factory=WorkerImageLimits)
    container_memory_bytes: int = 536_870_912
    swap_bytes: int = 536_870_912
    cpu_millicores: int = 1000
    process_limit: int = 32
    input_files: int = 10_000
    input_bytes: int = 2_147_483_647
    staging_bytes: int = 2_147_483_647
    cache_bytes: int = 2_147_483_647
    result_bytes: int = 10_485_760
    result_count: int = 100
    results_per_user: int = 100
    request_bytes: int = 131_072
    stdout_bytes: int = 1_179_648
    stderr_bytes: int = 65_536
    control_seconds: int = 5
    termination_seconds: int = 5
    cleanup_interval_seconds: int = 30
    json_nodes: int = 100_000
    uid: int = 65534
    gid: int = 65534
    serving_processes: int = 1
    temporary_backend: str = "tmpfs-smoke"
    temporary_root: str = "/var/lib/outage-analytical/spill"
    temporary_filesystem_identity: str = "unconfigured"
    temporary_inodes: int = 4096
    temporary_layout_version: int = 1
    docker_executable: str = "/usr/local/bin/docker"
    network: str = "none"
    ipc: str = "none"
    read_only_root: bool = True
    drop_capabilities: tuple[str, ...] = ("ALL",)
    no_new_privileges: bool = True
    temporary_options: tuple[str, ...] = ("noexec", "nosuid", "nodev")
    mounts: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.docker_executable, str)
            or not self.docker_executable.startswith("/")
            or str(PurePosixPath(self.docker_executable)) != self.docker_executable
            or ".." in PurePosixPath(self.docker_executable).parts
            or any(c in self.docker_executable for c in ("\n", "\x00"))
            or len(self.docker_executable) > 4096
        ):
            raise ValueError("Explicit absolute Docker executable required")
        if re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id) is None:
            raise ValueError("Immutable analytical image identity required")
        if (
            not isinstance(self.daemon_endpoint, str)
            or not self.daemon_endpoint.startswith("unix:///")
            or any(c in self.daemon_endpoint for c in ("\n", "\x00", "?", "#"))
            or ".." in self.daemon_endpoint.split("/")
        ):
            raise ValueError("Explicit local Docker endpoint required")
        roots = (
            self.staging_root,
            self.cache_root,
            self.result_root,
            self.temporary_root,
        )
        for root in roots:
            if (
                not isinstance(root, str)
                or not root.startswith("/")
                or len(root) > 4096
                or "\x00" in root
                or str(PurePosixPath(root)) != root
                or ".." in PurePosixPath(root).parts
                or len(PurePosixPath(root).parts) < 3
            ):
                raise ValueError("Private absolute runtime roots required")
        if any(
            a == b or a in PurePosixPath(b).parents
            for i, a in enumerate(map(PurePosixPath, roots))
            for j, b in enumerate(map(PurePosixPath, roots))
            if i != j
        ):
            raise ValueError("Separate private runtime roots required")
        for value in (
            self.platform,
            self.daemon_version,
            self.filesystem_identity,
            self.temporary_filesystem_identity,
        ):
            if not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError("Runtime platform identity required")
        integer_bounds = (
            "container_memory_bytes",
            "swap_bytes",
            "cpu_millicores",
            "process_limit",
            "input_files",
            "input_bytes",
            "staging_bytes",
            "cache_bytes",
            "result_bytes",
            "result_count",
            "results_per_user",
            "request_bytes",
            "stdout_bytes",
            "stderr_bytes",
            "control_seconds",
            "termination_seconds",
            "cleanup_interval_seconds",
            "json_nodes",
            "temporary_inodes",
        )
        if any(
            type(getattr(self, name)) is not int or not 0 < getattr(self, name) <= 2**40
            for name in integer_bounds
        ):
            raise ValueError("Finite positive runtime bounds required")
        if self.worker != WorkerImageLimits():
            raise ValueError("Worker limits must match internal v1 image profile")
        if (
            type(self.preview_lifetime_seconds) is not int
            or self.preview_lifetime_seconds != LIFETIME_SECONDS
            or type(self.result_lifetime_seconds) is not int
            or self.result_lifetime_seconds != LIFETIME_SECONDS
            or type(self.protocol_version) is not int
            or self.protocol_version != WORKER_PROTOCOL_VERSION
            or self.engine_version != "1.5.6"
            or type(self.uid) is not int
            or self.uid != 65534
            or type(self.gid) is not int
            or self.gid != 65534
            or type(self.serving_processes) is not int
            or self.serving_processes != 1
            or self.network != "none"
            or self.ipc != "none"
            or self.read_only_root is not True
            or self.no_new_privileges is not True
            or self.drop_capabilities != ("ALL",)
            or self.temporary_options != ("noexec", "nosuid", "nodev")
            or self.mounts != ()
            or self.environment != ()
            or self.temporary_backend not in {"tmpfs-smoke", "quota-disk"}
            or type(self.temporary_layout_version) is not int
            or self.temporary_layout_version != 1
            or self.swap_bytes != self.container_memory_bytes
            or self.container_memory_bytes
            <= self.worker.memory_bytes + self.worker.temporary_bytes
            or self.request_bytes > 131_072
            or self.stdout_bytes > 1_179_648
            or self.stdout_bytes < self.worker.output_bytes
            or self.input_files > 10_000
            or self.results_per_user > self.result_count
            or self.input_bytes > self.staging_bytes
        ):
            raise ValueError("Unsupported analytical isolation profile")

    @property
    def identity(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self))).hexdigest()

    @property
    def execution_bounds(self) -> ExecutionBounds:
        w = self.worker
        return ExecutionBounds(
            w.preparation_seconds,
            w.overall_seconds,
            w.memory_bytes,
            w.temporary_bytes,
            w.output_bytes,
            w.execution_seconds,
        )

    @property
    def encoding_bounds(self) -> EncodingBounds:
        w = self.worker
        return EncodingBounds(
            w.max_cell_bytes,
            w.max_depth,
            w.max_nested_items,
            w.max_columns,
            w.max_schema_bytes,
        )


@dataclass(frozen=True)
class RuntimeEvidence:
    profile_identity: str
    controlled_report: str
    isolation_report: str
    termination_report: str
    storage_report: str
    measurement_report: str
    reviewer: str
    reviewed_on: date
    acceptance_scope: str = "complete-runtime"

    def __post_init__(self) -> None:
        if not isinstance(self.acceptance_scope, str) or self.acceptance_scope not in {
            "complete-runtime",
            "local-preview-sql",
        }:
            raise ValueError("Unsupported analytical acceptance scope")
        for name, value in vars(self).items():
            if name == "reviewed_on":
                if type(value) is not date:
                    raise ValueError("Evidence review date required")
            elif not isinstance(value, str) or not value or len(value) > 256:
                raise ValueError("Bounded nonsecret evidence identity required")
        if re.fullmatch(r"[0-9a-f]{64}", self.profile_identity) is None:
            raise ValueError("Evidence profile identity required")
        for value in (
            self.controlled_report,
            self.isolation_report,
            self.termination_report,
            self.storage_report,
            self.measurement_report,
        ):
            if re.fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValueError("Evidence report digest required")

    def require_ready(
        self, profile: RuntimeProfile, *, started: bool, local_acceptance: bool = False
    ) -> None:
        if (
            started is not True
            or (
                self.acceptance_scope == "local-preview-sql"
                and local_acceptance is not True
            )
            or profile.temporary_backend != "quota-disk"
            or self.profile_identity != profile.identity
        ):
            raise RuntimeUnavailableError("Reviewed analytical runtime unavailable")


def read_runtime_config(path: "Path") -> tuple[RuntimeProfile, RuntimeEvidence | None]:
    """Read one bounded strict nonsecret profile and optional reviewed record."""
    import json
    from dataclasses import fields

    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate runtime configuration key")
            result[key] = value
        return result

    with path.open("rb") as stream:
        raw = stream.read(65_537)
    try:
        if len(raw) > 65_536:
            raise ValueError()
        document = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(document, dict) or set(document) != {"profile", "evidence"}:
            raise ValueError()
        values = document["profile"]
        if not isinstance(values, dict) or set(values) - {
            f.name for f in fields(RuntimeProfile)
        }:
            raise ValueError()
        values = dict(values)
        if "worker" in values:
            values["worker"] = WorkerImageLimits(**values["worker"])
        for name in ("drop_capabilities", "temporary_options", "mounts"):
            if name in values:
                values[name] = tuple(values[name])
        if "environment" in values:
            values["environment"] = tuple(tuple(v) for v in values["environment"])
        profile = RuntimeProfile(**values)
        record = document["evidence"]
        if record is None:
            return profile, None
        if not isinstance(record, dict):
            raise ValueError()
        record = dict(record)
        record["reviewed_on"] = date.fromisoformat(record["reviewed_on"])
        return profile, RuntimeEvidence(**record)
    except (ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        raise ValueError("Invalid nonsecret analytical runtime configuration") from None
