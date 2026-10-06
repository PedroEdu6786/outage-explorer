"""Explicit Linux parser limits and one-slot ownership; never an in-process fallback."""

import json
import math
import os
import selectors
import signal
import subprocess
import sys
from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic
from typing import BinaryIO, cast

from outage_explorer.application.errors import (
    AnalyticalBusyError,
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.application.ports.sql_inspection import InspectedSql, SqlRejected
from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    REQUEST_LIMIT,
    RESPONSE_LIMIT,
    VERSION,
    decode_scope,
)


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
    def __init__(self, bounds: InspectionBounds, *, python: str, prlimit: str) -> None:
        if not os.path.isabs(python) or not os.path.isabs(prlimit):
            raise ValueError("Explicit absolute inspection executables required")
        self.bounds, self.python, self.prlimit = bounds, python, prlimit
        self._slot, self._guard = Lock(), Lock()
        self._cancel = Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._running = False
        self._closed = False
        self._pid = os.getpid()

    def inspect(self, sql: str) -> InspectedSql:
        if os.getpid() != self._pid or sys.platform != "linux":
            raise RuntimeUnavailableError("Bounded SQL inspection unavailable")
        with self._guard:
            if self._running:
                raise AnalyticalBusyError("SQL inspection busy")
            if self._closed or self._process is not None:
                raise RuntimeUnavailableError("Bounded SQL inspection unavailable")
            if not self._slot.acquire(blocking=False):
                raise AnalyticalBusyError("SQL inspection busy")
            self._running = True
        try:
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
            raw = self._run(request, monotonic() + self.bounds.wall_seconds)
            try:
                return decode_scope(raw, sql)
            except (ValueError, TypeError, UnicodeError, RecursionError) as error:
                if isinstance(error, SqlRejected):
                    raise
                raise RuntimeUnavailableError(
                    "Invalid SQL inspection response"
                ) from None
        finally:
            with self._guard:
                self._running = False
                self._reap()
                self._slot.release()

    def _run(self, data: bytes, deadline: float) -> bytes:
        b = self.bounds
        try:
            self._process = subprocess.Popen(
                (
                    self.prlimit,
                    f"--as={b.memory_bytes}:{b.memory_bytes}",
                    f"--cpu={b.cpu_seconds}:{b.cpu_seconds}",
                    "--core=0:0",
                    "--fsize=0:0",
                    "--",
                    self.python,
                    "-I",
                    "-B",
                    "-m",
                    "outage_explorer.infrastructure.sql_validation.parser_process",
                ),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
                cwd="/",
                close_fds=True,
                start_new_session=True,
            )
        except OSError:
            raise RuntimeUnavailableError(
                "Bounded SQL inspection unavailable"
            ) from None
        p = self._process
        assert p.stdin is not None and p.stdout is not None and p.stderr is not None
        streams = (p.stdin, p.stdout, p.stderr)
        buffers = {p.stdout: bytearray(), p.stderr: bytearray()}
        offset = 0
        try:
            with selectors.DefaultSelector() as selector:
                for stream in streams:
                    os.set_blocking(stream.fileno(), False)
                selector.register(p.stdin, selectors.EVENT_WRITE)
                selector.register(p.stdout, selectors.EVENT_READ)
                selector.register(p.stderr, selectors.EVENT_READ)
                while selector.get_map():
                    remaining = deadline - monotonic()
                    if remaining <= 0 or self._cancel.is_set():
                        raise AnalyticalTimeoutError("SQL inspection interrupted")
                    for key, _ in selector.select(min(remaining, 0.05)):
                        stream = cast(BinaryIO, key.fileobj)
                        if stream is p.stdin:
                            try:
                                offset += os.write(
                                    stream.fileno(), data[offset : offset + 65536]
                                )
                            except BrokenPipeError:
                                offset = len(data)
                            if offset == len(data):
                                selector.unregister(stream)
                                stream.close()
                        else:
                            chunk = os.read(stream.fileno(), 4096)
                            if not chunk:
                                selector.unregister(stream)
                            else:
                                limit = (
                                    RESPONSE_LIMIT
                                    if stream is p.stdout
                                    else b.stderr_bytes
                                )
                                if len(buffers[stream]) + len(chunk) > limit:
                                    raise AnalyticalResourceError(
                                        "SQL inspection output limit exceeded"
                                    )
                                buffers[stream].extend(chunk)
                remaining = deadline - monotonic()
                if remaining <= 0 or self._cancel.is_set():
                    raise AnalyticalTimeoutError("SQL inspection interrupted")
                if p.wait(timeout=remaining) != 0 or buffers[p.stderr]:
                    raise RuntimeUnavailableError("Bounded SQL inspection failed")
            return bytes(buffers[p.stdout])
        except subprocess.TimeoutExpired:
            raise AnalyticalTimeoutError("SQL inspection interrupted") from None
        except OSError:
            raise RuntimeUnavailableError(
                "Bounded SQL inspection unavailable"
            ) from None
        finally:
            for stream in streams:
                stream.close()

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
