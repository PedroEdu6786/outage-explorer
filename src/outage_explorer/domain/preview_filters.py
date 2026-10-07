"""Exact facility identity and its bounded preview-filter representation."""

MAX_FACILITY_IDENTIFIER_BYTES = 256


class InvalidFacilityIdentifier(ValueError):
    """A supplied facility cannot be used as an exact preview identifier."""


def validate_facility_identifier(value: object) -> str:
    """Return the original string, or reject it without normalization."""
    if not isinstance(value, str) or not value:
        raise InvalidFacilityIdentifier("Facility must be a nonempty string")
    # Every UTF-8 character takes at least one byte. Reject long inputs before
    # encoding, so direct callers cannot allocate an unbounded encoded copy.
    if len(value) > MAX_FACILITY_IDENTIFIER_BYTES:
        raise InvalidFacilityIdentifier("Facility exceeds the UTF-8 byte limit")
    if value != value.strip():
        raise InvalidFacilityIdentifier("Facility has surrounding whitespace")
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x1F or 0x7F <= codepoint <= 0x9F:
            raise InvalidFacilityIdentifier("Facility contains a control character")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise InvalidFacilityIdentifier("Facility must be valid UTF-8") from error
    if len(encoded) > MAX_FACILITY_IDENTIFIER_BYTES:
        raise InvalidFacilityIdentifier("Facility exceeds the UTF-8 byte limit")
    return value
