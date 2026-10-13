"""Repository callers omit sessions; each decorated call owns its scope."""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session

from outage_explorer.infrastructure.postgresql.pool import BoundedPostgresqlPool
from outage_explorer.infrastructure.postgresql.session_scope import with_session


@pytest.fixture
def scope():
    pool = Mock(spec=BoundedPostgresqlPool)
    events = []
    sessions = []

    @contextmanager
    def session_scope():
        session = Mock(spec=Session)
        sessions.append(session)
        events.append("opened")
        try:
            yield session
        finally:
            events.append("closed")

    pool.session.side_effect = session_scope
    return pool, events, sessions


@pytest.mark.parametrize("keyword", [False, True])
def test_session_is_injected_and_closed_before_return(scope, keyword):
    pool, events, sessions = scope
    result = object()

    class Repository:
        def __init__(self):
            self._pool = pool

        @with_session
        def read(self, session, run_id, *, include_details=False):
            assert session is sessions[-1]
            assert run_id == "run-id"
            assert include_details is True
            events.append("queried")
            return result

    repository = Repository()
    for _ in range(2):
        if keyword:
            actual = repository.read(run_id="run-id", include_details=True)
        else:
            actual = repository.read("run-id", include_details=True)
        assert actual is result
        assert events[-3:] == ["opened", "queried", "closed"]

    assert sessions[0] is not sessions[1]
    assert repository.read.__name__ == "read"


def test_repository_exception_propagates_after_cleanup(scope):
    pool, events, _ = scope
    failure = ValueError("controlled mapping failure")

    class Repository:
        def __init__(self):
            self._pool = pool

        @with_session
        def read(self, session, run_id):
            raise failure

    with pytest.raises(ValueError) as error:
        Repository().read("run-id")

    assert error.value is failure
    assert events == ["opened", "closed"]
