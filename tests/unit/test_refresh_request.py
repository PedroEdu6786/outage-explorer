import pytest
from pydantic import ValidationError

from outage_explorer.application.refresh_request import RefreshAdmissionRequest


@pytest.mark.parametrize(
    "key", [1234567890123456, b"abcdefghijklmnop", "a" * 16 + "\n", "a" * 16 + "!"]
)
def test_direct_admission_inputs_reject_coercion_and_invalid_characters(key):
    with pytest.raises(ValidationError):
        RefreshAdmissionRequest(idempotency_key=key)


def test_admission_requires_key_and_rejects_extra_fields():
    for values in ({}, {"idempotency_key": "a" * 16, "start_date": "2026-04-02"}):
        with pytest.raises(ValidationError):
            RefreshAdmissionRequest.model_validate(values)


def test_validated_admission_key_cannot_be_mutated():
    admission = RefreshAdmissionRequest(idempotency_key="a" * 16)
    with pytest.raises(ValidationError):
        admission.idempotency_key = "invalid"
