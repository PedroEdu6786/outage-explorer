"""Lazy process-owned bounded PostgreSQL connections."""

import os
from collections.abc import Callable, Generator, Iterator
from contextlib import contextmanager
from threading import Lock
from typing import cast

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import DictRow, TupleRow, dict_row, tuple_row
from psycopg_pool import ConnectionPool
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

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


class _AccessConnectionPool(ConnectionPool[psycopg.Connection[DictRow]]):
    def _connect(self, timeout: float | None = None) -> psycopg.Connection[DictRow]:
        try:
            return super()._connect(timeout)
        except Exception:
            # Psycopg-pool logs connect failures. Never forward driver/SDK text.
            raise AccessStoreError("PostgreSQL connection failed") from None


class BoundedPostgresqlPool:
    def __init__(
        self, dsn: str, *, password_provider: Callable[[], str] | None = None
    ) -> None:
        self._dsn = validate_dsn(dsn)
        self._owner = os.getpid()
        self._pool: ConnectionPool[psycopg.Connection[DictRow]] | None = None
        self._closed = False
        self._lock = Lock()
        self._password_provider = password_provider
        if password_provider is not None and "password" in conninfo_to_dict(dsn):
            raise AccessConfigurationError("Mixed PostgreSQL credentials")
        self._orm_engine = create_engine(
            "postgresql+psycopg://",
            creator=self._orm_connection,
            poolclass=NullPool,
            hide_parameters=True,
        )

    def _connection_dsn(self) -> str:
        if os.getpid() != self._owner:
            raise AccessStoreError("PostgreSQL resources cannot cross processes")
        if self._password_provider is None:
            return self._dsn
        try:
            return make_conninfo(self._dsn, password=self._password_provider())
        except Exception:
            raise AccessStoreError("PostgreSQL credentials unavailable") from None

    def _get_pool(self) -> ConnectionPool[psycopg.Connection[DictRow]]:
        if os.getpid() != self._owner:
            raise AccessStoreError("PostgreSQL resources cannot cross processes")
        with self._lock:
            if self._closed:
                raise AccessStoreError("PostgreSQL resources are closed")
            if self._pool is None:
                self._pool = _AccessConnectionPool(
                    self._connection_dsn,
                    min_size=0,
                    max_size=4,
                    max_waiting=16,
                    timeout=3,
                    reconnect_timeout=3,
                    close_returns=True,
                    reset=self._reset_row_factory,
                    kwargs={
                        "row_factory": dict_row,
                        "connect_timeout": 3,
                        "options": "-c statement_timeout=5000 -c lock_timeout=1000 -c timezone=UTC",
                    },
                    open=False,
                )
                self._pool.open()
            return self._pool

    @staticmethod
    def _reset_row_factory(connection: psycopg.Connection[DictRow]) -> None:
        # ORM checkouts use tuples; existing SQL adapters expect dictionaries.
        connection.row_factory = dict_row

    def _orm_connection(self) -> psycopg.Connection[TupleRow]:
        connection = cast(psycopg.Connection[TupleRow], self._get_pool().getconn())
        connection.row_factory = tuple_row
        # close_returns=True returns this checkout when SQLAlchemy closes it.
        return connection

    @contextmanager
    def session(self) -> Generator[Session]:
        """Own one ORM transaction; never share its session across threads."""
        try:
            with Session(self._orm_engine) as session, session.begin():
                yield session
        except (SQLAlchemyError, psycopg.Error):
            raise AccessStoreError("PostgreSQL operation failed") from None
        except (TimeoutError, RuntimeError):
            raise AccessStoreError("PostgreSQL unavailable") from None

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
            self._orm_engine.dispose()
            if self._pool is not None:
                self._pool.close()
