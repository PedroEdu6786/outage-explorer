"""Lazy process-owned bounded PostgreSQL connections."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from outage_explorer.application.errors import (
    AccessConfigurationError,
    AccessStoreError,
)


def validate_dsn(dsn: str) -> str:
    """Permit explicit local targets or certificate-verified remote PostgreSQL."""
    try:
        values = conninfo_to_dict(dsn)
    except Exception:
        raise AccessConfigurationError("Invalid PostgreSQL configuration") from None
    host = str(values.get("host") or "")
    address = str(values.get("hostaddr") or "")
    local = host in {"localhost", "127.0.0.1", "::1"} or host.startswith("/")
    if (
        not host
        or "service" in values
        or "," in host
        or (address and address not in {"127.0.0.1", "::1"} and local)
        or (not local and values.get("sslmode") != "verify-full")
    ):
        raise AccessConfigurationError(
            "PostgreSQL requires an explicit local or TLS target"
        )
    return dsn


class BoundedPostgresqlPool:
    def __init__(self, dsn: str) -> None:
        self._dsn = validate_dsn(dsn)
        self._owner = os.getpid()
        self._pool: ConnectionPool[psycopg.Connection[DictRow]] | None = None
        self._closed = False
        self._lock = Lock()

    def _get_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        if os.getpid() != self._owner:
            raise AccessStoreError("PostgreSQL resources cannot cross processes")
        with self._lock:
            if self._closed:
                raise AccessStoreError("PostgreSQL resources are closed")
            if self._pool is None:
                self._pool = ConnectionPool(
                    self._dsn,
                    min_size=0,
                    max_size=4,
                    max_waiting=16,
                    timeout=3,
                    kwargs={
                        "row_factory": dict_row,
                        "connect_timeout": 3,
                        "options": "-c statement_timeout=5000 -c lock_timeout=1000 -c timezone=UTC",
                    },
                    open=False,
                )
                self._pool.open()
            return self._pool

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[DictRow]]:
        try:
            pool = self._get_pool()
            with pool.connection() as connection:
                yield connection
        except psycopg.Error:
            raise AccessStoreError("PostgreSQL operation failed") from None
        except (TimeoutError, RuntimeError):
            raise AccessStoreError("PostgreSQL unavailable") from None

    def close(self) -> None:
        if os.getpid() != self._owner:
            raise AccessStoreError("PostgreSQL resources cannot cross processes")
        with self._lock:
            self._closed = True
            if self._pool is not None:
                self._pool.close()
