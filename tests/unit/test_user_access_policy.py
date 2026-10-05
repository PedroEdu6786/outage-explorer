"""Pure role matrix over complete analytical scopes and refresh operations."""

from itertools import combinations

import pytest

from outage_explorer.domain.access import (
    AccessOperation,
    AnalyticalGrain,
    Role,
    permits_scope,
)

SCOPES = tuple(
    frozenset(scope)
    for size in range(1, 4)
    for scope in combinations(AnalyticalGrain, size)
)
REFRESH = tuple(
    operation
    for operation in AccessOperation
    if operation is not AccessOperation.ANALYTICAL
)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("grains", SCOPES)
def test_complete_analytical_role_matrix(role, grains):
    expected = role in (Role.ANALYST, Role.ADMIN) or grains == frozenset(
        {AnalyticalGrain.NATIONAL}
    )
    assert permits_scope(role, AccessOperation.ANALYTICAL, grains) is expected


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("operation", REFRESH)
def test_refresh_initiation_outcome_diagnostics_admin_only(role, operation):
    assert permits_scope(role, operation, frozenset()) is (role is Role.ADMIN)


@pytest.mark.parametrize(
    "role,operation,grains",
    [
        ("admin", AccessOperation.ANALYTICAL, frozenset({AnalyticalGrain.NATIONAL})),
        (None, AccessOperation.ANALYTICAL, frozenset({AnalyticalGrain.NATIONAL})),
        (Role.ADMIN, "analytical", frozenset({AnalyticalGrain.NATIONAL})),
        (Role.ADMIN, "unsupported", frozenset({AnalyticalGrain.NATIONAL})),
        (Role.ADMIN, None, frozenset()),
        (Role.ADMIN, AccessOperation.ANALYTICAL, frozenset()),
        (Role.ADMIN, AccessOperation.ANALYTICAL, frozenset({"national"})),
        (
            Role.ADMIN,
            AccessOperation.ANALYTICAL,
            frozenset({AnalyticalGrain.NATIONAL, "secret"}),
        ),
        (Role.ADMIN, AccessOperation.ANALYTICAL, {AnalyticalGrain.NATIONAL}),
        (Role.ADMIN, AccessOperation.ANALYTICAL, None),
        (
            Role.ADMIN,
            AccessOperation.REFRESH_INITIATE,
            frozenset({AnalyticalGrain.NATIONAL}),
        ),
    ],
)
def test_unsupported_untrusted_and_ambiguous_inputs_deny(role, operation, grains):
    assert permits_scope(role, operation, grains) is False
