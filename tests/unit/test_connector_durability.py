"""Default durable candidate orchestration through injected use cases."""

from dataclasses import replace
from unittest.mock import Mock

import pytest

from outage_explorer.application.dto import ConnectorInput, ConnectorResult
from outage_explorer.application.errors import (
    ConnectorConfigurationError,
    ConnectorDependencyError,
)
from outage_explorer.application.ports.artifacts import (
    ArtifactError,
    ArtifactLimitError,
)
from outage_explorer.application.ports.connector import DurableConnectorReceipt
from outage_explorer.application.services.connector_artifacts import (
    CreateDurableConnectorCandidate,
)
from tests.unit.test_connector_service import REFERENCE, setup


def local_result(outcome="candidate_verified", written=True):
    service, request, *_ = setup()
    result = service.run(request)
    return ConnectorResult(replace(result.report, outcome=outcome), written)


def test_failed_local_candidate_never_uploads():
    persist = Mock()
    result = CreateDurableConnectorCandidate(
        Mock(return_value=local_result("failed")), persist
    ).execute(ConnectorInput(None, None, "local"))
    assert result.receipt is None
    persist.assert_not_called()


@pytest.mark.parametrize(
    "failure,code",
    [
        (ArtifactError("secret"), "artifact_integrity"),
        (ArtifactLimitError("secret"), "resource"),
        (ConnectorConfigurationError("secret"), "configuration"),
        (ConnectorDependencyError("secret"), "aws_dependency"),
        (KeyboardInterrupt(), "interrupted"),
        (RuntimeError("secret"), "internal"),
    ],
)
def test_persistence_failure_keeps_local_reference_without_durable_success(
    failure, code
):
    local = local_result()
    result = CreateDurableConnectorCandidate(
        Mock(return_value=local), Mock(side_effect=failure)
    ).execute(ConnectorInput(None, None, "local"))
    assert result.candidate == local and result.error == code and result.receipt is None
    assert result.candidate.report.manifest == REFERENCE
    assert "secret" not in repr(result)


def test_inconsistent_durable_receipt_cannot_confirm_success():
    wrong = replace(REFERENCE, key="e" * 64, sha256="e" * 64)
    persist = Mock(return_value=DurableConnectorReceipt(wrong, 1, 10))
    result = CreateDurableConnectorCandidate(
        Mock(return_value=local_result()), persist
    ).execute(ConnectorInput(None, None, "local"))
    assert result.error == "artifact_integrity" and result.receipt is None


def test_missing_local_report_prevents_upload():
    persist = Mock()
    result = CreateDurableConnectorCandidate(
        Mock(return_value=local_result(written=False)), persist
    ).execute(ConnectorInput(None, None, "local"))
    assert result.error == "report" and result.receipt is None
    persist.assert_not_called()
