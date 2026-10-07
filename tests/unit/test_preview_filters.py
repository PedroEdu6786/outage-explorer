import json
from pathlib import Path

import pytest

from outage_explorer.domain.preview_filters import (
    MAX_FACILITY_IDENTIFIER_BYTES,
    InvalidFacilityIdentifier,
    validate_facility_identifier,
)


@pytest.mark.parametrize(
    "value",
    ["00123", "123", "A01", "a01", "A B", "x' OR 1=1 --", 'a"b', "é", "e\u0301"],
)
def test_valid_identity_is_preserved_exactly(value):
    assert validate_facility_identifier(value) == value


@pytest.mark.parametrize("value", ["x" * 256, "é" * 128, "😀" * 64])
def test_exact_utf8_byte_limit_is_accepted(value):
    assert len(value.encode("utf-8")) == MAX_FACILITY_IDENTIFIER_BYTES == 256
    assert validate_facility_identifier(value) == value


@pytest.mark.parametrize(
    "value", ["x" * 257, "é" * 128 + "x", "😀" * 64 + "x", "é" * 129]
)
def test_values_over_utf8_byte_limit_are_rejected(value):
    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier(value)


@pytest.mark.parametrize("value", [None, 123, 0, True, b"A01", ["A01"], {"id": "A01"}])
def test_non_string_values_are_rejected(value):
    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier(value)


@pytest.mark.parametrize("value", ["", " ", " A01", "A01 ", "\u00a0A01", "A01\u2003"])
def test_empty_or_surrounding_whitespace_is_rejected(value):
    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier(value)


@pytest.mark.parametrize("codepoint", [*range(0x20), *range(0x7F, 0xA0)])
def test_every_unicode_cc_control_is_rejected_inside_an_identifier(codepoint):
    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier("A" + chr(codepoint) + "B")


@pytest.mark.parametrize("value", ["\ud800", "A\udfffB", "\ud83d\ude00"])
def test_surrogate_codepoints_are_rejected_instead_of_repaired(value):
    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier(value)


def test_overlong_direct_input_is_rejected_before_encoding():
    class OverlongString(str):
        def encode(self, *args, **kwargs):
            pytest.fail("An already oversized string must not be encoded")

    with pytest.raises(InvalidFacilityIdentifier):
        validate_facility_identifier(OverlongString("x" * 257))


PROPOSED_EXAMPLES = json.loads(
    (
        Path(__file__).parents[2]
        / "docs/specs/preview-facility-filter/contract-cases.json"
    ).read_text()
)


@pytest.mark.parametrize(
    "case", PROPOSED_EXAMPLES["cases"], ids=lambda case: case["name"]
)
def test_proposed_examples_obey_the_pure_identifier_rule(case):
    # Request outcomes also involve authorization/dataset/cursor/HTTP rules.
    # This phase proves only the identifier validity labeled in each example.
    values = [value for name, value in case["query_parameters"] if name == "facility"]
    if case["facility_identifier_valid"] is None:
        assert values == []
        return
    assert values
    for value in values:
        if case["facility_identifier_valid"]:
            assert validate_facility_identifier(value) == value
        else:
            with pytest.raises(InvalidFacilityIdentifier):
                validate_facility_identifier(value)
