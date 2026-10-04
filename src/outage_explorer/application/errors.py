"""Failures independent of transport status codes."""

from typing import Literal


class VerificationError(Exception):
    """Invalid evidence, arithmetic invariant, or unsuccessful report write."""


class ConnectorConfigurationError(ValueError):
    """Invalid explicit configuration; messages contain no supplied values."""


class ConnectorReportError(Exception):
    """Progress or final report could not be persisted within its bounds."""


ConnectorFailure = Literal[
    "configuration",
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
