"""Downstream spies prove fresh authorization precedes direct and page work."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from outage_explorer.application.errors import (
    AccessStoreError,
    ForbiddenError,
    UnauthenticatedError,
)
from outage_explorer.application.services.access import AccessService
from outage_explorer.domain.access import (
    AccessOperation,
    AnalyticalGrain,
    Role,
    SeededUser,
    Session,
)
from tests.unit.test_user_access_policy import REFRESH, SCOPES

NOW = datetime(2026, 10, 4, tzinfo=UTC)
TOKEN = "a" * 43


class Clock:
    def __init__(self):
        self.time = NOW

    def now(self):
        return self.time


class Security:
    def digest(self, token):
        return "digest:" + token


class Store:
    def __init__(self, role):
        self.session = Session(
            Security().digest(TOKEN),
            SeededUser(
                "seeded", "https://trusted.test/pool", "subject", "seeded@test", role
            ),
            NOW,
            NOW + timedelta(hours=1),
        )
        self.calls = 0
        self.failure = False

    def resolve_session(self, digest, now):
        self.calls += 1
        if self.failure:
            raise AccessStoreError("Store unavailable")
        return (
            self.session
            if self.session and digest == self.session.token_digest
            else None
        )


class DownstreamSpy:
    """Represents a future use case; references belong to its server-side plan."""

    def __init__(self, access, operation, referenced_grains):
        self.access = access
        self.operation = operation
        self.references = referenced_grains
        self.events = []
        self.data_calls = 0
        self.execution_calls = 0
        self.worker_inputs = []

    def invoke(
        self, token=TOKEN, *, page=1, claimed_role="admin", claimed_dataset="national"
    ):
        # Untrusted labels are deliberately absent from the authorization call.
        authorized = self.access.authorize(
            token, self.operation, grains=self.references
        )
        self.events.append(("authorized", authorized))
        self.data_calls += 1
        self.execution_calls += 1
        self.worker_inputs.append(authorized.grains)
        return {"protected": "server data", "page": page}


@pytest.fixture
def harness():
    def build(
        role,
        operation=AccessOperation.ANALYTICAL,
        grains=frozenset({AnalyticalGrain.NATIONAL}),
    ):
        store, clock = Store(role), Clock()
        access = AccessService(store, Security(), clock)
        return DownstreamSpy(access, operation, grains), store, clock

    return build


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("grains", SCOPES)
def test_direct_and_later_pages_complete_scope_matrix(harness, role, grains):
    spy, store, _ = harness(role, grains=grains)
    allowed = role in (Role.ANALYST, Role.ADMIN) or grains == frozenset(
        {AnalyticalGrain.NATIONAL}
    )
    for page in (1, 2, 3):
        if allowed:
            assert spy.invoke(page=page)["page"] == page
            principal = spy.events[-1][1]
            assert principal.principal.role is role and principal.grains == grains
        else:
            with pytest.raises(ForbiddenError, match="^Access denied$") as error:
                spy.invoke(page=page)
            assert "protected" not in str(error.value) + repr(error.value)
    assert store.calls == 3
    assert spy.data_calls == spy.execution_calls == (3 if allowed else 0)
    assert spy.worker_inputs == ([grains] * 3 if allowed else [])


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("operation", REFRESH)
def test_admin_refresh_matrix_and_untrusted_claims(harness, role, operation):
    spy, store, _ = harness(role, operation, frozenset())
    if role is Role.ADMIN:
        assert spy.invoke(claimed_role="viewer")
    else:
        with pytest.raises(ForbiddenError):
            spy.invoke(claimed_role="admin")
        assert spy.data_calls == spy.execution_calls == 0
    assert store.calls == 1


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "malformed",
        "unknown",
        "expired",
        "future",
        "revoked",
        "unassigned",
        "unavailable",
        "wrong_digest",
    ],
)
@pytest.mark.parametrize("operation", list(AccessOperation))
def test_invalid_sessions_never_reach_data_or_execution(harness, failure, operation):
    grains = (
        frozenset({AnalyticalGrain.NATIONAL})
        if operation is AccessOperation.ANALYTICAL
        else frozenset()
    )
    spy, store, clock = harness(Role.ADMIN, operation, grains)
    token = TOKEN
    if failure == "missing":
        token = ""
    elif failure == "malformed":
        token = "☃" * 43
    elif failure == "unknown":
        token = "b" * 43
    elif failure == "expired":
        clock.time = store.session.expires_at
    elif failure == "future":
        clock.time = NOW - timedelta(microseconds=1)
    elif failure == "revoked":
        store.session = None
    elif failure == "unassigned":
        store.session = replace(
            store.session, user=replace(store.session.user, role=None)
        )
    elif failure == "unavailable":
        store.failure = True
    else:
        store.session = replace(store.session, token_digest="different")
        # Exercise a faulty adapter returning a mismatched digest too.
        store.resolve_session = lambda digest, now: store.session
    expected = AccessStoreError if failure == "unavailable" else UnauthenticatedError
    with pytest.raises(expected) as error:
        spy.invoke(token)
    assert not spy.events and not spy.worker_inputs
    assert spy.data_calls == spy.execution_calls == 0
    assert "server data" not in str(error.value) + repr(error.value)


@pytest.mark.parametrize("change", ["role", "revoked", "expired", "unavailable"])
def test_later_result_page_rechecks_current_state(harness, change):
    spy, store, clock = harness(
        Role.ANALYST,
        grains=frozenset({AnalyticalGrain.NATIONAL, AnalyticalGrain.FACILITY}),
    )
    assert spy.invoke(page=1)
    if change == "role":
        store.session = replace(
            store.session, user=replace(store.session.user, role=Role.VIEWER)
        )
        expected = ForbiddenError
    elif change == "revoked":
        store.session = None
        expected = UnauthenticatedError
    elif change == "expired":
        clock.time = store.session.expires_at
        expected = UnauthenticatedError
    else:
        store.failure = True
        expected = AccessStoreError
    for page in (2, 3):
        with pytest.raises(expected):
            spy.invoke(page=page, claimed_role="admin", claimed_dataset="national")
    assert store.calls == 3
    assert spy.data_calls == spy.execution_calls == 1


def test_broad_scope_and_role_cannot_be_supplied_by_caller(harness):
    spy, store, _ = harness(
        Role.VIEWER,
        grains=frozenset({AnalyticalGrain.NATIONAL, AnalyticalGrain.GENERATOR}),
    )
    with pytest.raises(ForbiddenError):
        spy.invoke(claimed_role="admin", claimed_dataset="national")
    with pytest.raises(TypeError):
        spy.access.authorize(
            TOKEN, AccessOperation.ANALYTICAL, grains=spy.references, role=Role.ADMIN
        )
    assert spy.data_calls == spy.execution_calls == 0 and store.calls == 1


@pytest.mark.parametrize(
    "operation,grains",
    [
        ("analytical", frozenset({AnalyticalGrain.NATIONAL})),
        (AccessOperation.ANALYTICAL, frozenset()),
        (AccessOperation.ANALYTICAL, frozenset({"national"})),
        (AccessOperation.ANALYTICAL, frozenset({AnalyticalGrain.NATIONAL, "unknown"})),
        (AccessOperation.REFRESH_DIAGNOSTIC, frozenset({AnalyticalGrain.FACILITY})),
    ],
)
def test_invalid_operation_scope_never_accesses_payload(harness, operation, grains):
    spy, store, _ = harness(Role.ADMIN, operation, grains)
    with pytest.raises(ForbiddenError):
        spy.invoke()
    assert store.calls == 1 and spy.data_calls == spy.execution_calls == 0
