"""Suppress provider wire logs while secrets are in flight."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager


class _QuietWire(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(_WIRE, "active", False)


_WIRE = threading.local()


@contextmanager
def quiet_provider_wire() -> Iterator[None]:
    filters = [
        (logging.getLogger(name), _QuietWire())
        for name in (
            "httpx",
            "httpcore",
            "httpcore.connection",
            "httpcore.http11",
            "httpcore.http2",
        )
    ]
    for logger, quiet in filters:
        logger.addFilter(quiet)
    previous = getattr(_WIRE, "active", False)
    _WIRE.active = True
    try:
        yield
    finally:
        _WIRE.active = previous
        for logger, quiet in filters:
            logger.removeFilter(quiet)
