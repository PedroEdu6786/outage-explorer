"""Failures independent of transport status codes."""

from typing import Literal


class VerificationError(Exception):
    """Invalid evidence, arithmetic invariant, or unsuccessful report write."""


class ConnectorConfigurationError(ValueError):
    """Invalid explicit configuration; messages contain no supplied values."""


class ConnectorDependencyError(Exception):
    """AWS SDK login support is missing; never exposes SDK exception text."""


class ConnectorReportError(Exception):
    """Progress or final report could not be persisted within its bounds."""


ConnectorFailure = Literal[
    "configuration",
    "aws_dependency",
    "prior_integrity",
    "retrieval",
    "resource",
    "representation",
    "artifact_integrity",
    "unusable_input",
    "report",
    "interrupted",
    "internal",
]


class AccessConfigurationError(ValueError):
    """Invalid setup/input; never includes supplied credentials or values."""


class AccessStoreError(Exception):
    """Operational store unavailable; callers must fail closed."""


class SeedConflictError(Exception):
    """Existing provisioned identity differs; transaction was rolled back."""


class UnauthenticatedError(Exception):
    """Missing or invalid verified identity/session."""


class ForbiddenError(Exception):
    """Recognized identity lacks the required role."""


class LoginAttemptLimitError(Exception):
    """Transient login admission bound reached."""


class InvalidRequestError(ValueError):
    """Invalid transport input; contains no supplied values."""


class RefreshBusyError(Exception):
    """An admitted or unresolved refresh already occupies coordination."""


class IdempotencyConflictError(Exception):
    """A scoped key is already bound to a different request identity."""


class StaleRefreshOwnerError(Exception):
    """The worker no longer holds the unexpired fenced ownership lease."""
