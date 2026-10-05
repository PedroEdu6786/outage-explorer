"""Pure identity and operational access value types; no credentials."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    VIEWER = "viewer"
    ANALYST = "analyst"
    ADMIN = "admin"


@dataclass(frozen=True)
class SeededUser:
    id: str
    identity_issuer: str
    identity_subject: str
    email: str
    role: Role


@dataclass(frozen=True)
class Session:
    token_digest: str
    user: SeededUser
    established_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class LoginAttempt:
    state_digest: str
    browser_binding_digest: str
    pkce_verifier: str = field(repr=False)
    callback_uri: str
    return_to: str
    created_at: datetime
    expires_at: datetime


class AccessOperation(StrEnum):
    ANALYTICAL = "analytical"
    REFRESH_INITIATE = "refresh_initiate"
    REFRESH_OUTCOME = "refresh_outcome"
    REFRESH_DIAGNOSTIC = "refresh_diagnostic"


class AnalyticalGrain(StrEnum):
    NATIONAL = "national"
    FACILITY = "facility"
    GENERATOR = "generator"


def permits_scope(
    role: Role,
    operation: AccessOperation,
    grains: frozenset[AnalyticalGrain],
) -> bool:
    """Decide a complete trusted scope; unsupported or ambiguous inputs deny."""
    if (
        not isinstance(role, Role)
        or not isinstance(operation, AccessOperation)
        or not isinstance(grains, frozenset)
        or any(not isinstance(grain, AnalyticalGrain) for grain in grains)
    ):
        return False
    if operation is AccessOperation.ANALYTICAL:
        return bool(grains) and (
            role in (Role.ANALYST, Role.ADMIN)
            or grains == frozenset({AnalyticalGrain.NATIONAL})
        )
    return not grains and role is Role.ADMIN


@dataclass(frozen=True)
class AuthorizedAccess:
    principal: SeededUser
    grains: frozenset[AnalyticalGrain]
