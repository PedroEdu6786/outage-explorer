"""Shared limits and strict JSON object decoding for the parser protocol."""

VERSION = 1
REQUEST_LIMIT = 6 * 65_536 + 1024
RESPONSE_LIMIT = 1024


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate inspection field")
        result[key] = value
    return result
