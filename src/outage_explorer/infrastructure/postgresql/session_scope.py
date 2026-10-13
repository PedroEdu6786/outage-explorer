"""Inject bounded sessions into repository operations and transaction contexts."""

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from functools import wraps
from typing import Concatenate, Protocol

from sqlalchemy.orm import Session

from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool


class _SessionOwner(Protocol):
    @property
    def _pool(self) -> BoundedPostgresqlPool: ...


def with_session[Owner: _SessionOwner, **Parameters, Result](
    operation: Callable[Concatenate[Owner, Session, Parameters], Result],
) -> Callable[Concatenate[Owner, Parameters], Result]:
    """Own a session per call; decorated calls do not share a transaction."""

    @wraps(operation)
    def wrapped(
        self: Owner, /, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Result:
        with self._pool.session() as session:
            return operation(self, session, *args, **kwargs)

    return wrapped


def with_session_context[Owner: _SessionOwner, **Parameters, Result](
    operation: Callable[Concatenate[Owner, Session, Parameters], Generator[Result]],
) -> Callable[Concatenate[Owner, Parameters], AbstractContextManager[Result]]:
    """Keep one session open until the caller exits the returned context."""

    @wraps(operation)
    @contextmanager
    def wrapped(
        self: Owner, /, *args: Parameters.args, **kwargs: Parameters.kwargs
    ) -> Generator[Result]:
        with self._pool.session() as session:
            yield from operation(self, session, *args, **kwargs)

    return wrapped
