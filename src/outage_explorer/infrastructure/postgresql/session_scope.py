"""Inject one short-lived session into a repository method."""

from collections.abc import Callable
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
