"""Bounded local Docker control. Candidate implementation, not readiness evidence."""

import json
import os
import re
import selectors
import signal
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import monotonic
from typing import BinaryIO, Protocol, cast

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.execution import (
    ExecutionBounds,
    PreviewRead,
    PreviewRows,
    QueryRead,
)
from outage_explorer.application.ports.query_results import QueryOutput
from outage_explorer.infrastructure.worker_runtime.configuration import RuntimeProfile
from outage_explorer.infrastructure.worker_runtime.decoding import WorkerTransport
from outage_explorer.infrastructure.worker_runtime.inputs import (
    StagedInputs,
    stage_inputs,
)
from outage_explorer.infrastructure.worker_runtime.ownership import OwnershipLedger
from outage_explorer.infrastructure.worker_runtime.quota import (
    DiskSpill,
    validate_native_daemon,
)


@dataclass(frozen=True)
class ControlResult:
    code: int
    stdout: bytes
    stderr: bytes


class DockerControl(Protocol):
    def run(
        self,
        arguments: tuple[str, ...],
        *,
        data: bytes,
        deadline: float,
        stdout_bytes: int,
        stderr_bytes: int,
        cancel: Event | None = None,
    ) -> ControlResult: ...


class BoundedDockerControl:
    def __init__(
        self, endpoint: str, executable: str = "/usr/local/bin/docker"
    ) -> None:
        if not endpoint.startswith("unix:///") or not os.path.isabs(executable):
            raise ValueError("Explicit local Docker control required")
        self.endpoint, self.executable = endpoint, executable
        self._unreaped: list[subprocess.Popen[bytes]] = []

    def run(
        self,
        arguments: tuple[str, ...],
        *,
        data: bytes = b"",
        deadline: float,
        stdout_bytes: int = 8192,
        stderr_bytes: int = 65536,
        cancel: Event | None = None,
    ) -> ControlResult:
        if self._unreaped:
            raise RuntimeUnavailableError("Analytical controller death unconfirmed")
        if monotonic() >= deadline:
            raise AnalyticalTimeoutError("Analytical control deadline exceeded")
        # No inherited credential/config/DOCKER_HOST/PATH environment. No shell.
        try:
            process = subprocess.Popen(
                (self.executable, "--host", self.endpoint, *arguments),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={
                    "PATH": "/usr/bin:/bin",
                    "HOME": "/nonexistent",
                    "DOCKER_CONFIG": "/nonexistent",
                },
                start_new_session=True,
            )
        except OSError:
            raise RuntimeUnavailableError("Analytical control unavailable") from None
        assert (
            process.stdin is not None
            and process.stdout is not None
            and process.stderr is not None
        )
        streams = (process.stdin, process.stdout, process.stderr)
        buffers = {process.stdout: bytearray(), process.stderr: bytearray()}
        offset = 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream in streams:
                    os.set_blocking(stream.fileno(), False)
                if data:
                    selector.register(process.stdin, selectors.EVENT_WRITE)
                else:
                    process.stdin.close()
                selector.register(process.stdout, selectors.EVENT_READ)
                selector.register(process.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - monotonic()
                    if remaining <= 0 or cancel is not None and cancel.is_set():
                        raise AnalyticalTimeoutError("Analytical control interrupted")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        selected = key.fileobj
                        stream = cast(BinaryIO, selected)
                        if stream is process.stdin:
                            try:
                                offset += os.write(
                                    process.stdin.fileno(),
                                    data[offset : offset + 65536],
                                )
                            except BrokenPipeError:
                                offset = len(data)
                            if offset == len(data):
                                selector.unregister(stream)
                                process.stdin.close()
                        else:
                            assert stream is process.stdout or stream is process.stderr
                            chunk = os.read(stream.fileno(), 65536)
                            if not chunk:
                                selector.unregister(stream)
                            else:
                                buffer = buffers[stream]
                                bound = (
                                    stdout_bytes
                                    if stream is process.stdout
                                    else stderr_bytes
                                )
                                if len(buffer) + len(chunk) > bound:
                                    raise AnalyticalResourceError(
                                        "Analytical control output limit exceeded"
                                    )
                                buffer.extend(chunk)
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise AnalyticalTimeoutError("Analytical control deadline exceeded")
                code = process.wait(timeout=remaining)
            return ControlResult(
                code, bytes(buffers[process.stdout]), bytes(buffers[process.stderr])
            )
        except subprocess.TimeoutExpired:
            raise AnalyticalTimeoutError(
                "Analytical control deadline exceeded"
            ) from None
        except OSError:
            raise RuntimeUnavailableError("Analytical control unavailable") from None
        finally:
            # Kill the whole host-control process group, including inherited-pipe
            # children. Container liveness is independently inspected/reaped.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._unreaped.append(process)
                raise RuntimeUnavailableError(
                    "Analytical controller death unconfirmed"
                ) from None
            finally:
                for stream in streams:
                    stream.close()

    def reap(self, deadline: float) -> None:
        for process in tuple(self._unreaped):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise RuntimeUnavailableError("Analytical controller death unconfirmed")
            try:
                process.wait(timeout=min(remaining, 1))
            except subprocess.TimeoutExpired:
                raise RuntimeUnavailableError(
                    "Analytical controller death unconfirmed"
                ) from None
            self._unreaped.remove(process)


class DockerRuntime:
    def __init__(
        self, profile: RuntimeProfile, control: DockerControl, ledger: OwnershipLedger
    ) -> None:
        if isinstance(control, BoundedDockerControl) and (
            control.endpoint != profile.daemon_endpoint
            or control.executable != profile.docker_executable
        ):
            raise ValueError("Docker endpoint/profile mismatch")
        self.profile, self.control, self.ledger = profile, control, ledger
        self.transport = WorkerTransport(profile)
        self.cancel = Event()
        self._staging: StagedInputs | None = None
        self._container: str | None = None
        self._intended = False
        self._removed = False
        self._death_confirmed = False
        self._removal_attempted = False
        self._spill: DiskSpill | None = None
        self._create_attempted = False

    def validate_temporary_backend(self) -> None:
        """Explicit startup probe; inert construction never touches the host."""
        if self.profile.temporary_backend != "quota-disk":
            return
        self._validate_daemon()
        spill = DiskSpill(self.profile, self.ledger.owner)
        spill.open()
        spill.release()

    def _validate_daemon(self) -> None:
        raw = self._control(
            (
                "info",
                "--format",
                '{"version":{{json .ServerVersion}},"os":{{json .OSType}},'
                '"kernel":{{json .KernelVersion}},"name":{{json .Name}},'
                '"architecture":{{json .Architecture}}}',
            ),
            monotonic() + self.profile.control_seconds,
        ).stdout
        validate_native_daemon(self.profile, raw)

    def _control(
        self,
        arguments: tuple[str, ...],
        deadline: float,
        *,
        data: bytes = b"",
        attach: bool = False,
    ) -> ControlResult:
        result = self.control.run(
            arguments,
            data=data,
            deadline=deadline
            if attach
            else min(deadline, monotonic() + self.profile.control_seconds),
            stdout_bytes=self.profile.stdout_bytes if attach else 8192,
            stderr_bytes=self.profile.stderr_bytes,
            cancel=self.cancel if attach else None,
        )
        if not attach and result.code != 0:
            raise RuntimeUnavailableError("Analytical control failed")
        return result

    def _create_arguments(self) -> tuple[str, ...]:
        p = self.profile
        args = [
            "create",
            "--name",
            "outage-analytical-" + self.ledger.owner,
            "--label",
            "outage.analytical.owner=" + self.ledger.owner,
            "--network",
            "none",
            "--ipc",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            f"{p.uid}:{p.gid}",
            "--memory",
            str(p.container_memory_bytes),
            "--memory-swap",
            str(p.swap_bytes),
            "--cpus",
            str(p.cpu_millicores / 1000),
            "--pids-limit",
            str(p.process_limit),
            "--log-driver",
            "none",
            "--restart",
            "no",
            "--interactive",
        ]
        if p.temporary_backend == "tmpfs-smoke":
            args.extend(
                (
                    "--tmpfs",
                    f"/tmp:rw,noexec,nosuid,nodev,size={p.worker.temporary_bytes},uid={p.uid},gid={p.gid},mode=700",
                )
            )
        else:
            if self._spill is None:
                raise RuntimeUnavailableError(
                    "Analytical temporary backend unavailable"
                )
            args.extend(("--mount", self._spill.mount_argument()))
        assert self._staging is not None
        if self._staging.files:
            directory = str(self._staging.directory)
            if any(c in directory for c in (",", "\n", "\x00")):
                raise RuntimeUnavailableError("Unsupported analytical mount path")
            args.extend(
                (
                    "--mount",
                    "type=bind,src="
                    + directory
                    + ",dst=/inputs,readonly,bind-recursive=disabled",
                )
            )
        args.append(p.image_id)
        if sum(len(a) + 1 for a in args) > p.request_bytes:
            raise AnalyticalResourceError("Analytical mount argument limit exceeded")
        return tuple(args)

    def _run(
        self, request: PreviewRead | QueryRead, bounds: ExecutionBounds, deadline: float
    ) -> PreviewRows | QueryOutput:
        if (
            bounds != self.profile.execution_bounds
            or self._staging is not None
            or self._intended
        ):
            raise RuntimeUnavailableError("Analytical runtime state unavailable")
        data = self.transport.request(request)
        files = (
            request.files
            if isinstance(request, PreviewRead)
            else tuple(f for _, files in request.relations for f in files)
        )
        # Preparation shares the caller's overall deadline; launcher reserves the
        # slot before downloads. Worker execution starts only after staging.
        self._staging = stage_inputs(
            self.profile, files, min(deadline, monotonic() + bounds.preparation_seconds)
        )
        if self.cancel.is_set():
            raise RuntimeUnavailableError("Analytical execution cancelled")
        self.prepare_temporary()
        arguments = self._create_arguments()
        self.ledger.creating()
        self._create_attempted = True
        created = self._control(arguments, deadline)
        container = created.stdout.decode("ascii", errors="strict").strip()
        if re.fullmatch(r"[0-9a-f]{64}", container) is None:
            raise RuntimeUnavailableError("Invalid analytical container identity")
        self._container = container
        response = self._control(
            ("start", "--attach", "--interactive", container),
            deadline,
            data=data,
            attach=True,
        )
        state = self._inspect(deadline)
        if state["Running"] is not False or state["Restarting"] is not False:
            raise RuntimeUnavailableError("Analytical worker death unconfirmed")
        if response.code != state["ExitCode"]:
            raise RuntimeUnavailableError("Analytical attach status mismatch")
        if state["OOMKilled"] is True:
            raise AnalyticalResourceError("Analytical worker resource exhausted")
        return self.transport.decode(
            response.stdout, request=request, exit_code=response.code
        )

    def prepare_temporary(self) -> None:
        """Persist spill/staging intent before creating worker-accessible state."""
        assert self._staging is not None
        if self.profile.temporary_backend == "quota-disk":
            self.validate_temporary_backend()
            self._spill = DiskSpill(self.profile, self.ledger.owner)
            self._spill.open()
        self.ledger.intend(
            str(self._staging.directory),
            spill=str(self._spill.directory) if self._spill is not None else None,
            preparing=True,
        )
        self._intended = True
        if self._spill is not None:
            self._spill.allocate()

    def preview(
        self, request: PreviewRead, bounds: ExecutionBounds, deadline: float
    ) -> PreviewRows:
        try:
            return cast(PreviewRows, self._run(request, bounds, deadline))
        except AnalyticalTimeoutError:
            raise AnalyticalResourceError(
                "Analytical preview deadline exceeded"
            ) from None
        except (UnicodeError, ValueError, OSError):
            raise RuntimeUnavailableError("Analytical runtime failed") from None

    def query(
        self, request: QueryRead, bounds: ExecutionBounds, deadline: float
    ) -> QueryOutput:
        try:
            return cast(QueryOutput, self._run(request, bounds, deadline))
        except (UnicodeError, ValueError, OSError):
            raise RuntimeUnavailableError("Analytical runtime failed") from None

    def _inspect(self, deadline: float) -> dict[str, object]:
        identity = self._container or "outage-analytical-" + self.ledger.owner
        raw = self._control(
            (
                "inspect",
                "--format",
                '{"Id":{{json .Id}},"Owner":{{json (index .Config.Labels "outage.analytical.owner")}},"State":{{json .State}}}',
                identity,
            ),
            deadline,
        ).stdout
        try:
            value = json.loads(raw)
            state = value["State"]
            if (
                value["Owner"] != self.ledger.owner
                or re.fullmatch(r"[0-9a-f]{64}", value["Id"]) is None
                or self._container is not None
                and value["Id"] != self._container
                or any(
                    type(state[k]) is not bool
                    for k in ("Running", "Restarting", "OOMKilled")
                )
                or type(state["ExitCode"]) is not int
            ):
                raise ValueError()
            self._container = value["Id"]
            return cast(dict[str, object], state)
        except (ValueError, TypeError, KeyError):
            raise RuntimeUnavailableError(
                "Invalid analytical ownership state"
            ) from None

    def terminate_and_reap(self) -> None:
        try:
            self._cleanup()
        except (OSError, ValueError):
            raise RuntimeUnavailableError("Analytical cleanup unavailable") from None

    def _cleanup(self) -> None:
        deadline = monotonic() + self.profile.termination_seconds
        if isinstance(self.control, BoundedDockerControl):
            self.control.reap(deadline)
        if self._intended and self._create_attempted and not self._removed:
            if self._death_confirmed and self._removal_attempted:
                assert self._container is not None
                listing = self._control(
                    (
                        "container",
                        "ls",
                        "--all",
                        "--no-trunc",
                        "--filter",
                        "id=" + self._container,
                        "--format",
                        "{{.ID}}",
                    ),
                    deadline,
                ).stdout
                if listing.strip() == b"":
                    self._removed = True
            if not self._removed:
                self._reap_container(deadline)
        if self._intended and self._removed:
            self.ledger.removed()
        if self._spill is not None:
            self._spill.close()
        if self._staging is not None:
            self._staging.close()
            self._staging = None
        if self._intended:
            self.ledger.clear()
        if self._spill is not None:
            self._spill.release()
            self._spill = None
        self._container = None
        self._intended = self._removed = False
        self._death_confirmed = self._removal_attempted = False
        self._create_attempted = False
        self.cancel.clear()

    def _reap_container(self, deadline: float) -> None:
        state = self._inspect(deadline)
        assert self._container is not None
        if state["Running"] or state["Restarting"]:
            self._control(("kill", self._container), deadline)
        self._control(("wait", self._container), deadline)
        state = self._inspect(deadline)
        if state["Running"] or state["Restarting"]:
            raise RuntimeUnavailableError("Analytical worker death unconfirmed")
        self._death_confirmed = True
        self._removal_attempted = True
        self._control(("rm", self._container), deadline)
        self._removed = True

    def recover_owned(self) -> None:
        """After acquiring the dead owner's lock, reconcile its exact intent."""
        record = self.ledger.read()
        if record is None:
            return
        staging = Path(record["staging"])
        root = Path(self.profile.staging_root)
        no_worker = record.get("phase") in {"preparing", "removed"}
        if (
            staging.parent != root
            or not staging.name.startswith("execution-")
            or staging.is_symlink()
            or not staging.exists()
            and not no_worker
            or staging.exists()
            and (
                not staging.is_dir()
                or staging.stat().st_uid != os.getuid()
                or stat.S_IMODE(staging.stat().st_mode) not in {0o555, 0o700}
            )
        ):
            raise RuntimeUnavailableError("Invalid orphan analytical staging")
        current_owner = self.ledger.owner
        self.ledger.owner = record["owner"]
        self._intended = True
        self._create_attempted = record.get("phase", "creating") == "creating"
        self._removed = self._death_confirmed = record.get("phase") == "removed"
        self._staging = StagedInputs(staging, ()) if staging.exists() else None
        try:
            if "spill" in record:
                if self.profile.temporary_backend != "quota-disk":
                    raise RuntimeUnavailableError("Analytical spill profile changed")
                self._spill = DiskSpill(self.profile, record["owner"])
                if record["spill"] != str(self._spill.directory):
                    raise RuntimeUnavailableError("Invalid orphan analytical spill")
                self._validate_daemon()
                self._spill.open(recovering=True)
            elif self.profile.temporary_backend == "quota-disk":
                raise RuntimeUnavailableError("Analytical spill ownership missing")
            self.terminate_and_reap()
        finally:
            self.ledger.owner = current_owner
