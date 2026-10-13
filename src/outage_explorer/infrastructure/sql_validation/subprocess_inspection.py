"""Explicit Linux parser limits and one-slot ownership; never an in-process fallback."""

import hashlib
import json
import math
import os
import signal
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock
from time import monotonic

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.sql_inspection import InspectedSql, SqlRejected
from outage_explorer.infrastructure.sql_validation.ownership import ParserOwnership
from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    REQUEST_LIMIT,
    VERSION,
    decode_scope,
)
from outage_explorer.infrastructure.sql_validation.subprocess_transport import exchange


@dataclass(frozen=True)
class InspectionBounds:
    wall_seconds: float
    cpu_seconds: int
    memory_bytes: int
    termination_seconds: float
    stderr_bytes: int
    max_sql_bytes: int
    max_nodes: int
    max_depth: int

    def __post_init__(self) -> None:
        for value in (self.wall_seconds, self.termination_seconds):
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("Positive finite inspection bounds required")
        for value in (
            self.cpu_seconds,
            self.memory_bytes,
            self.stderr_bytes,
            self.max_sql_bytes,
            self.max_nodes,
            self.max_depth,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("Positive inspection bounds required")
        if (
            self.max_sql_bytes > 65_536
            or self.max_nodes > 10_000
            or self.max_depth > 64
        ):
            raise ValueError("Inspection protocol limits exceeded")


class UnavailableSqlInspector:
    def inspect(self, sql: str) -> InspectedSql:
        raise RuntimeUnavailableError("Bounded SQL inspection unavailable")


class SubprocessSqlInspector:
    def __init__(
        self,
        bounds: InspectionBounds,
        *,
        python: str,
        prlimit: str,
        setpriv: str,
        ownership_root: Path,
        executable_hashes: tuple[str, str, str] | None = None,
    ) -> None:
        if any(
            not isinstance(path, str) or not os.path.isabs(path) or "\x00" in path
            for path in (python, prlimit, setpriv)
        ):
            raise ValueError("Explicit absolute inspection executables required")
        self.bounds, self.python, self.prlimit = bounds, python, prlimit
        self.setpriv = setpriv
        self.executable_hashes = executable_hashes
        self._ownership = ParserOwnership(ownership_root)
        self._slot, self._guard = Lock(), Lock()
        self._cancel = Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._running = False
        self._closed = False
        self._pid = os.getpid()

    def start(self) -> None:
        self._require_owner()
        with self._guard:
            if self._closed:
                raise RuntimeUnavailableError("Bounded SQL inspection unavailable")
            self._verify_executables()
            self._ownership.open()

    def _verify_executables(self) -> None:
        if self.executable_hashes is None:
            return
        for path, expected in zip(
            (self.python, self.prlimit, self.setpriv),
            self.executable_hashes,
            strict=True,
        ):
            try:
                with open(path, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or not 0 < info.st_size <= 64 * 1024**2
                    ):
                        raise OSError
                    actual = hashlib.file_digest(stream, "sha256").hexdigest()
                if actual != expected:
                    raise OSError
            except OSError:
                raise RuntimeUnavailableError(
                    "SQL inspection executable identity mismatch"
                ) from None

    def inspect(self, sql: str) -> InspectedSql:
        self._require_owner()
        with self._guard:
            if self._running:
                raise AnalyticalBusyError("SQL inspection busy")
            if self._closed or self._process is not None or self._ownership.fd is None:
                raise RuntimeUnavailableError("Bounded SQL inspection unavailable")
            if not self._slot.acquire(blocking=False):
                raise AnalyticalBusyError("SQL inspection busy")
            self._running = True
        try:
            request = self._encode_request(sql)
            raw = self._run(request, monotonic() + self.bounds.wall_seconds)
            try:
                return decode_scope(raw, sql)
            except SqlRejected:
                raise
            except (ValueError, TypeError, UnicodeError, RecursionError):
                raise RuntimeUnavailableError(
                    "Invalid SQL inspection response"
                ) from None
        finally:
            with self._guard:
                self._running = False
                self._reap()
                self._slot.release()

    def _require_owner(self) -> None:
        if os.getpid() != self._pid or sys.platform != "linux":
            raise RuntimeUnavailableError("Bounded SQL inspection unavailable")

    def _encode_request(self, sql: str) -> bytes:
        try:
            if (
                type(sql) is not str
                or len(sql) > self.bounds.max_sql_bytes
                or len(sql.encode("utf-8")) > self.bounds.max_sql_bytes
            ):
                raise SqlRejected("invalid_sql")
        except UnicodeError:
            raise SqlRejected("invalid_sql") from None
        request = json.dumps(
            {
                "version": VERSION,
                "sql": sql,
                "max_sql_bytes": self.bounds.max_sql_bytes,
                "max_nodes": self.bounds.max_nodes,
                "max_depth": self.bounds.max_depth,
            },
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        if len(request) > REQUEST_LIMIT:
            raise SqlRejected("invalid_sql")
        return request

    def _run(self, data: bytes, deadline: float) -> bytes:
        try:
            self._process = subprocess.Popen(
                self._command(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                cwd="/",
                close_fds=True,
                pass_fds=(self._ownership.fd,)
                if self._ownership.fd is not None
                else (),
                start_new_session=True,
            )
        except OSError:
            raise RuntimeUnavailableError(
                "Bounded SQL inspection unavailable"
            ) from None
        return exchange(
            self._process,
            data,
            deadline=deadline,
            stderr_bytes=self.bounds.stderr_bytes,
            cancel=self._cancel,
        )

    def _command(self) -> tuple[str, ...]:
        bounds = self.bounds
        return (
            self.setpriv,
            "--pdeathsig",
            "KILL",
            "--no-new-privs",
            "--",
            self.prlimit,
            f"--as={bounds.memory_bytes}:{bounds.memory_bytes}",
            f"--cpu={bounds.cpu_seconds}:{bounds.cpu_seconds}",
            "--core=0:0",
            "--fsize=0:0",
            "--",
            self.python,
            "-I",
            "-B",
            "-m",
            "outage_explorer.infrastructure.sql_validation.parser_process",
            str(self._pid),
            str(self._ownership.fd),
        )

    def _reap(self) -> None:
        p = self._process
        if p is None:
            return
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError:
            raise RuntimeUnavailableError("SQL inspection death unconfirmed") from None
        try:
            p.wait(timeout=self.bounds.termination_seconds)
            os.killpg(p.pid, 0)
        except ProcessLookupError:
            self._process = None
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise RuntimeUnavailableError("SQL inspection death unconfirmed")

    def close(self) -> None:
        if os.getpid() != self._pid:
            raise RuntimeUnavailableError("SQL inspection ownership unavailable")
        self._cancel.set()
        with self._guard:
            self._closed = True
            if self._running:
                raise RuntimeUnavailableError("SQL inspection shutdown pending")
            self._reap()
            if self._slot.locked():
                self._slot.release()
            self._ownership.close()
