"""Bounded stdin/stdout/stderr exchange with the SQL parser child."""

import os
import selectors
import subprocess
from threading import Event
from time import monotonic
from typing import IO, cast

from outage_explorer.application.errors import (
    AnalyticalResourceError,
    AnalyticalTimeoutError,
    RuntimeUnavailableError,
)
from outage_explorer.infrastructure.sql_validation.subprocess_protocol import (
    RESPONSE_LIMIT,
)


def _send_request(
    selector: selectors.BaseSelector, stream: IO[bytes], data: bytes, offset: int
) -> int:
    try:
        offset += os.write(stream.fileno(), data[offset : offset + 65536])
    except BrokenPipeError:
        offset = len(data)
    if offset == len(data):
        selector.unregister(stream)
        stream.close()
    return offset


def _receive_output(
    selector: selectors.BaseSelector,
    stream: IO[bytes],
    buffer: bytearray,
    limit: int,
) -> None:
    chunk = os.read(stream.fileno(), 4096)
    if not chunk:
        selector.unregister(stream)
        return
    if len(buffer) + len(chunk) > limit:
        raise AnalyticalResourceError("SQL inspection output limit exceeded")
    buffer.extend(chunk)


def exchange(
    process: subprocess.Popen[bytes],
    data: bytes,
    *,
    deadline: float,
    stderr_bytes: int,
    cancel: Event,
) -> bytes:
    """Exchange one request, requiring complete bounded output and clean exit."""
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdin, stdout, stderr = process.stdin, process.stdout, process.stderr
    streams = (stdin, stdout, stderr)
    output, errors = bytearray(), bytearray()
    offset = 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream in streams:
                os.set_blocking(stream.fileno(), False)
            selector.register(stdin, selectors.EVENT_WRITE)
            selector.register(stdout, selectors.EVENT_READ)
            selector.register(stderr, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - monotonic()
                if remaining <= 0 or cancel.is_set():
                    raise AnalyticalTimeoutError("SQL inspection interrupted")
                for key, _ in selector.select(min(remaining, 0.05)):
                    stream = cast(IO[bytes], key.fileobj)
                    if stream is stdin:
                        offset = _send_request(selector, stdin, data, offset)
                    elif stream is stdout:
                        _receive_output(selector, stdout, output, RESPONSE_LIMIT)
                    else:
                        _receive_output(selector, stderr, errors, stderr_bytes)
            remaining = deadline - monotonic()
            if remaining <= 0 or cancel.is_set():
                raise AnalyticalTimeoutError("SQL inspection interrupted")
            if process.wait(timeout=remaining) != 0 or errors:
                raise RuntimeUnavailableError("Bounded SQL inspection failed")
        return bytes(output)
    except subprocess.TimeoutExpired:
        raise AnalyticalTimeoutError("SQL inspection interrupted") from None
    except OSError:
        raise RuntimeUnavailableError("Bounded SQL inspection unavailable") from None
    finally:
        for stream in streams:
            stream.close()
