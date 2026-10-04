"""Keep synchronous connector wire diagnostics out of application logs.

HTTPX can log credential-bearing URLs and httpcore can log echoed response
headers or transport exceptions. A context-local filter suppresses their wire
logs while retrieving a source response. It never captures secrets and passes
through unrelated requests, including concurrent requests in other threads.
Application-level source failures remain available as safe reason messages.

Filters are installed on first use, not import. They deliberately stay installed
as pass-through filters outside the scope, avoiding removal races. Logger names
cover the pinned HTTPX/httpcore transports, including lazily loaded protocols.
Custom injected transports must respect this logging boundary and must not
start background logging under unrelated logger names.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpx

_SOURCE_WIRE: ContextVar[bool] = ContextVar("eia_source_wire", default=False)
_WIRE_LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
)


class _SourceWireFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _SOURCE_WIRE.get()


_FILTER = _SourceWireFilter()


@contextmanager
def source_response(
    transport: httpx.BaseTransport, request: httpx.Request
) -> Iterator[httpx.Response]:
    """Protect opening, streaming and closing a response; caller owns transport."""
    for name in _WIRE_LOGGERS:
        logging.getLogger(name).addFilter(_FILTER)
    token = _SOURCE_WIRE.set(True)
    try:
        response = transport.handle_request(request)
        try:
            yield response
        finally:
            response.close()
    finally:
        _SOURCE_WIRE.reset(token)
